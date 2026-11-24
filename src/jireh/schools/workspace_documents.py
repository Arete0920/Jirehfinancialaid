"""Disposable, exact-fixture file selection and encrypted document readback.

Only the two generated fictional PDFs can be stored. Never route this adapter
in the standalone runtime, or substitute its fixture scanner for antivirus.
"""
from uuid import UUID, uuid4

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST, require_http_methods, require_safe

from jireh.financial_aid.document_lifecycle import (
    DocumentLifecycleError, _authorized_draft, create_synthetic_document,
    delete_synthetic_document, read_synthetic_document,
)
from jireh.financial_aid.models import FinancialDocument
from jireh.financial_aid.synthetic_document_views import (
    _ALLOWED_FIXTURES, _POLICY, _backend, _error, PrivateDocumentStorageError,
)
from .customer_workspace import _page

_ALLOWED_URLCONFS = frozenset((
    "jireh.schools.demo_urls", "jireh.schools.customer_workspace_urls",
))


def _scope(request, school_id, household_id, academic_year_id):
    if (
        getattr(settings, "JIREH_SYNTHETIC_DOCUMENTS_ONLY", False) is not True
        or settings.ROOT_URLCONF not in _ALLOWED_URLCONFS
    ):
        raise PermissionDenied("Fictional documents disabled.")
    if request.GET:
        raise ValueError("query_parameters_not_supported")
    return dict(user=request.user, school_id=school_id, household_id=household_id,
                academic_year_id=academic_year_id)


def _pdf(data):
    response = HttpResponse(data, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="fictional-sample.pdf"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _key(request):
    value = request.headers.get("X-Document-Request-Key", "")
    if len(value) != 36:
        raise ValueError("invalid_key")
    parsed = UUID(value)
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError("invalid_key")
    return value


def _selected_bytes(request):
    # Raw PDF bytes avoid multipart parsing, temporary upload files and
    # retention of client-supplied names. Never trust declared MIME alone.
    length = request.META.get("CONTENT_LENGTH", "")
    if request.content_type != "application/pdf":
        raise ValueError("invalid_body")
    if not length.isascii() or not length.isdecimal() or len(length) > 4:
        raise ValueError("invalid_body")
    count = int(length)
    if not 0 < count <= _POLICY.maximum_bytes:
        raise ValueError("invalid_body")
    data = request.read(count + 1)
    if len(data) != count or data not in _ALLOWED_FIXTURES:
        raise ValueError("invalid_body")
    return data


@ensure_csrf_cookie
@require_safe
def workspace_documents(request, school_id, household_id, academic_year_id):
    try:
        scope = _scope(request, school_id, household_id, academic_year_id)
        with transaction.atomic():
            draft = _authorized_draft(**scope, lock=True)
            rows = list(FinancialDocument.objects.for_school(draft.school_id).filter(
                application=draft, household_id=draft.household_id,
                state__in=(FinancialDocument.STATE_ACTIVE, FinancialDocument.STATE_DELETE_PENDING),
            ).order_by("-version").values("id", "version", "byte_count", "state")[:51])
    except (PermissionDenied, Http404, ValueError) as exc:
        return _error(exc)
    return _page(
        request, "documents", household=draft.household, year=draft.academic_year,
        documents=rows[:50], documents_truncated=len(rows) > 50,
        document_request_key=str(uuid4()), document_max_bytes=_POLICY.maximum_bytes,
    )


@require_GET
def workspace_document_sample(request, school_id, household_id, academic_year_id, variant):
    try:
        scope = _scope(request, school_id, household_id, academic_year_id)
        _authorized_draft(**scope, lock=False)
        if variant not in ("original", "corrected"):
            raise Http404("Fictional document not found.")
    except (PermissionDenied, Http404, ValueError) as exc:
        return _error(exc)
    return _pdf(_ALLOWED_FIXTURES[variant == "corrected"])


@csrf_protect
@require_POST
def workspace_document_upload(request, school_id, household_id, academic_year_id):
    try:
        scope = _scope(request, school_id, household_id, academic_year_id)
        _authorized_draft(**scope, lock=False)
    except (PermissionDenied, Http404, ValueError) as exc:
        return _error(exc)
    try:
        key = _key(request)
        data = _selected_bytes(request)
    except (ValueError, OSError):
        return JsonResponse({"detail": "Only the exact fictional sample PDFs are accepted."}, status=400)
    try:
        row = create_synthetic_document(
            **scope, request_key=key, category="FICTIONAL_TAX",
            data=data, policy=_POLICY, backend=_backend(),
        )
    except (PermissionDenied, Http404, ValidationError, IntegrityError, DocumentLifecycleError,
            PrivateDocumentStorageError, OSError) as exc:
        return _error(exc)
    return JsonResponse({"document_id": str(row.pk), "version": row.version, "demo_only": True})


@require_GET
def workspace_document_read(request, school_id, household_id, academic_year_id, document_id):
    try:
        scope = _scope(request, school_id, household_id, academic_year_id)
        _authorized_draft(**scope, lock=False)
        data = read_synthetic_document(**scope, document_id=document_id, backend=_backend())
    except (PermissionDenied, Http404, DocumentLifecycleError,
            PrivateDocumentStorageError, OSError, ValueError) as exc:
        return _error(exc)
    return _pdf(data)


@csrf_protect
@require_http_methods(["DELETE"])
def workspace_document_remove(request, school_id, household_id, academic_year_id, document_id):
    try:
        scope = _scope(request, school_id, household_id, academic_year_id)
        _authorized_draft(**scope, lock=False)
        if request.read(1):
            return JsonResponse({"detail": "No request body accepted."}, status=400)
        delete_synthetic_document(**scope, document_id=document_id, backend=_backend())
    except (PermissionDenied, Http404, DocumentLifecycleError,
            PrivateDocumentStorageError, OSError, ValidationError, ValueError) as exc:
        return _error(exc)
    return JsonResponse({"demo_only": True, "status": "FICTIONAL_DOCUMENT_DELETED"})
