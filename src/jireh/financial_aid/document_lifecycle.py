"""Scoped synthetic document lifecycle with durable metadata and injected storage.

Functional only with JIREH_SYNTHETIC_DOCUMENTS_ONLY in disposable test settings
and an explicitly identified synthetic storage/scanner test double. Real
financial uploads require separately certified encrypted storage and malware
scanning, stream limits, retention, privacy review and operational acceptance.
No customer HTTP routes are exported.
"""
import hashlib
import uuid
from dataclasses import dataclass
from typing import Protocol

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Max
from django.http import Http404
from django.utils import timezone

from jireh.schools.access import require_household_access
from jireh.schools.models import HouseholdAccess, School
from .models import AidApplication, FinancialDocument, FinancialDocumentEvent


class DocumentLifecycleError(ValueError):
    """Stable, non-sensitive error code; no contents or object keys in errors."""


class SyntheticDocumentDeletionBackend(Protocol):
    synthetic_only: bool
    private_storage: bool
    encrypted_storage: bool

    def delete(self, object_key: str) -> None: ...


class SyntheticDocumentBackend(SyntheticDocumentDeletionBackend, Protocol):
    def inspect(self, data: bytes) -> tuple[str, bool]: ...
    def put(self, object_key: str, data: bytes) -> None: ...
    def get(self, object_key: str) -> bytes: ...


@dataclass(frozen=True, slots=True)
class SyntheticDocumentPolicy:
    version: str
    allowed_categories: tuple[str, ...]
    allowed_media_types: tuple[str, ...]
    maximum_bytes: int


def _deny(reason):
    raise DocumentLifecycleError(reason)


def _require_deletion_backend(backend):
    if getattr(settings, "JIREH_SYNTHETIC_DOCUMENTS_ONLY", False) is not True:
        raise PermissionDenied("Financial document service is not activated.")
    if not all(
        getattr(backend, name, False) is True
        for name in ("synthetic_only", "private_storage", "encrypted_storage")
    ):
        _deny("synthetic_backend_required")
    if not callable(getattr(backend, "delete", None)):
        _deny("synthetic_backend_required")


def _require_backend(backend):
    _require_deletion_backend(backend)
    for method in ("inspect", "put", "get"):
        if not callable(getattr(backend, method, None)):
            _deny("synthetic_backend_required")


def _validate_policy(policy, category, data):
    if (
        type(policy) is not SyntheticDocumentPolicy
        or type(policy.version) is not str
        or not policy.version
        or len(policy.version) > 64
        or type(policy.allowed_categories) is not tuple
        or not policy.allowed_categories
        or any(type(x) is not str or not x or len(x) > 48
               for x in policy.allowed_categories)
        or len(set(policy.allowed_categories)) != len(policy.allowed_categories)
        or type(policy.allowed_media_types) is not tuple
        or not policy.allowed_media_types
        or any(type(x) is not str or not x or len(x) > 96
               for x in policy.allowed_media_types)
        or len(set(policy.allowed_media_types)) != len(policy.allowed_media_types)
        or type(policy.maximum_bytes) is not int
        or not 1 <= policy.maximum_bytes <= 2**31 - 1
    ):
        _deny("document_policy_invalid")
    if type(category) is not str or category not in policy.allowed_categories:
        _deny("document_category_denied")
    if type(data) is not bytes or not 0 < len(data) <= policy.maximum_bytes:
        _deny("document_size_denied")


def _authorized_draft(user, school_id, household_id, academic_year_id, *, lock):
    household = require_household_access(
        user, school_id=school_id, household_id=household_id
    )
    if lock:
        # Serialize reads and writes with the school-first grant revocation service.
        if not School.objects.select_for_update().filter(
            pk=household.school_id, is_active=True,
        ).exists():
            raise Http404("Document application not found.")
        if not HouseholdAccess.objects.select_for_update().filter(
            household_id=household.pk, household__school_id=household.school_id,
            household__is_active=True, user_id=user.pk, user__is_active=True,
            is_active=True,
        ).exists():
            raise Http404("Document application not found.")
    query = AidApplication.objects.for_school(household.school_id).filter(
        household_id=household.pk, academic_year_id=academic_year_id,
        status=AidApplication.STATUS_DRAFT,
    )
    if lock:
        query = query.select_for_update()
    application = query.first()
    if application is None:
        raise Http404("Document application not found.")
    return application


@transaction.atomic
def create_synthetic_document(
    *, user, school_id, household_id, academic_year_id,
    request_key, category, data, policy, backend
):
    """Create a single versioned document after scan and school-grant checks."""
    _require_backend(backend)
    _validate_policy(policy, category, data)
    if type(request_key) is not str:
        _deny("document_request_key_invalid")
    try:
        requested = uuid.UUID(request_key)
    except (ValueError, TypeError, AttributeError):
        _deny("document_request_key_invalid")
    if str(requested) != request_key:
        _deny("document_request_key_invalid")
    application = _authorized_draft(
        user, school_id, household_id, academic_year_id, lock=True,
    )
    sha = hashlib.sha256(data).hexdigest()
    existing = FinancialDocument.objects.for_school(application.school_id).filter(
        application=application, request_key=requested,
    ).first()
    if existing is not None:
        if (
            existing.sha256 != sha or existing.category != category
            or existing.byte_count != len(data)
        ):
            _deny("document_request_conflict")
        if existing.state != FinancialDocument.STATE_ACTIVE:
            _deny("document_not_active")
        return existing

    # Bound disposable storage even when clients repeatedly request new versions.
    # Existing idempotent retries were handled above and do not consume capacity.
    if FinancialDocument.objects.filter(application=application).count() >= 50:
        _deny("document_version_limit_reached")

    detected_type, clean = backend.inspect(data)
    if clean is not True:
        _deny("document_scan_rejected")
    if type(detected_type) is not str or detected_type not in policy.allowed_media_types:
        _deny("document_detected_type_denied")
    version = (
        FinancialDocument.objects.filter(application=application)
        .aggregate(last=Max("version"))["last"] or 0
    ) + 1
    document = FinancialDocument(
        school_id=application.school_id,
        household_id=application.household_id,
        application=application,
        created_by=user,
        request_key=requested,
        version=version,
        category=category,
        detected_media_type=detected_type,
        byte_count=len(data),
        sha256=sha,
    )
    key = str(document.object_key)
    try:
        backend.put(key, data)
        document.save()
        FinancialDocumentEvent.objects.create(
            school_id=application.school_id,
            document=document, actor_user=user,
            action=FinancialDocumentEvent.ACTION_CREATED,
        )
    except Exception:
        try:
            backend.delete(key)
        except Exception:
            # The backend must use an operational orphan-reaper. Never expose
            # orphan storage keys or their underlying content to callers.
            pass
        raise
    return document


@transaction.atomic
def read_synthetic_document(
    *, user, school_id, household_id, academic_year_id, document_id, backend
) -> bytes:
    """Serialize protected reads with deletion's fail-closed tombstone."""
    _require_backend(backend)
    application = _authorized_draft(
        user, school_id, household_id, academic_year_id, lock=True,
    )
    row = FinancialDocument.objects.for_school(application.school_id).select_for_update().filter(
        application=application, household_id=application.household_id,
        pk=document_id, state=FinancialDocument.STATE_ACTIVE,
    ).first()
    if row is None:
        raise Http404("Document not found.")
    try:
        data = backend.get(str(row.object_key))
    except Exception:
        _deny("document_storage_read_failed")
    if (
        type(data) is not bytes
        or len(data) != row.byte_count
        or hashlib.sha256(data).hexdigest() != row.sha256
    ):
        _deny("document_integrity_failed")
    return data


def delete_synthetic_document(
    *, user, school_id, household_id, academic_year_id, document_id, backend
):
    """Retryable fail-closed two-phase removal; no download while pending."""
    _require_backend(backend)
    with transaction.atomic():
        application = _authorized_draft(
            user, school_id, household_id, academic_year_id, lock=True,
        )
        row = FinancialDocument.objects.for_school(application.school_id).select_for_update().filter(
            application=application, household_id=application.household_id,
            pk=document_id,
        ).first()
        if row is None:
            raise Http404("Document not found.")
        if row.state == FinancialDocument.STATE_DELETED:
            return row
        if row.state == FinancialDocument.STATE_ACTIVE:
            row.state = FinancialDocument.STATE_DELETE_PENDING
            row.save(update_fields=["state", "updated_at"])
    # The pending tombstone commits before the backend call: storage failure
    # cannot make document content readable to application clients.
    _remove_ciphertext(row, backend)
    with transaction.atomic():
        row = FinancialDocument.objects.select_for_update().get(pk=row.pk)
        if row.state == FinancialDocument.STATE_DELETE_PENDING:
            _finish_document_deletion(row, user.pk)
    return row


@transaction.atomic(durable=True)
def recover_synthetic_document_deletion(
    *, operator, school_id, document_id, backend: SyntheticDocumentDeletionBackend,
):
    """Finish a committed tombstone for a trusted caller's authenticated operator.

    The disposable profile assigns exact (operator ID, school UUID) pairs in
    JIREH_SYNTHETIC_DOCUMENT_RECOVERY_ASSIGNMENTS. No assignment is implicit.
    """
    _require_deletion_backend(backend)
    assignments = getattr(settings, "JIREH_SYNTHETIC_DOCUMENT_RECOVERY_ASSIGNMENTS", ())
    users = get_user_model()
    if (not isinstance(operator, users) or type(school_id) is not uuid.UUID
            or not isinstance(assignments, (tuple, frozenset))
            or (operator.pk, school_id) not in assignments):
        raise PermissionDenied("Document recovery assignment required.")
    if not School.objects.select_for_update().filter(pk=school_id, is_active=True).exists():
        raise Http404("Document not found.")
    if not users.objects.select_for_update().filter(
        pk=operator.pk, is_active=True, is_staff=True, is_superuser=False,
    ).exists():
        raise PermissionDenied("Document recovery assignment required.")
    row = FinancialDocument.objects.for_school(school_id).select_for_update().only(
        "school_id", "object_key", "state",
    ).filter(
        pk=document_id, application__status=AidApplication.STATUS_DRAFT,
        state__in=(FinancialDocument.STATE_DELETE_PENDING, FinancialDocument.STATE_DELETED),
    ).first()
    if row is None:
        raise Http404("Document not found.")
    if row.state == FinancialDocument.STATE_DELETE_PENDING:
        _remove_ciphertext(row, backend)
        _finish_document_deletion(row, operator.pk)


def _remove_ciphertext(row, backend):
    try:
        backend.delete(str(row.object_key))
    except Exception:
        raise DocumentLifecycleError("document_storage_delete_failed") from None


def _finish_document_deletion(row, actor_id):
    row.state = FinancialDocument.STATE_DELETED
    row.deleted_at = timezone.now()
    row.save(update_fields=["state", "deleted_at", "updated_at"])
    FinancialDocumentEvent.objects.create(
        school_id=row.school_id, document=row, actor_user_id=actor_id,
        action=FinancialDocumentEvent.ACTION_DELETED,
    )
