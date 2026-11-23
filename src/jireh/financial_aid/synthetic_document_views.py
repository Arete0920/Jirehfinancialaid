"""Test-only, school-scoped fictional document HTTP lifecycle.

This adapter accepts NO uploaded bytes: the only document is a fixed, generated
PDF with no financial information. The disposable backend uses actual AES-GCM
for local evidence; its fixed-fixture scanner is NOT antivirus or production
malware certification. Production URLConf never imports this module.
"""
import json
import secrets
import tempfile
from functools import lru_cache
from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .document_lifecycle import (
    DocumentLifecycleError, SyntheticDocumentPolicy, create_synthetic_document,
    read_synthetic_document, delete_synthetic_document,
)
# Encrypted document support is optional in the existing localhost demo:
# a missing preproduction cryptography wheel must not break other demo routes.
try:
    from .local_encrypted_backend import (
        LocalEncryptedClamdBackend, PrivateDocumentStorageError,
    )
except ImportError:
    LocalEncryptedClamdBackend = None

    class PrivateDocumentStorageError(ValueError):
        """Local fictional encrypted storage is unavailable (fail closed)."""
from .models import FinancialDocument
from .services import selected_student_ids_for_draft


_ALLOWED_URLCONFS = frozenset(("jireh.schools.urls", "jireh.schools.demo_urls"))
_POLICY = SyntheticDocumentPolicy(
    version="fictional-local-document-v1",
    allowed_categories=("FICTIONAL_TAX",),
    allowed_media_types=("application/pdf",),
    maximum_bytes=4096,
)


def _fictional_pdf():
    """Generate a tiny valid, one-page PDF without personal or financial data."""
    stream = b"BT /F1 12 Tf 40 730 Td (JIREH FICTIONAL SAMPLE - NOT A TAX RECORD) Tj ET"
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode("ascii")
        + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    )
    sections = [b"%PDF-1.4\n"]
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(sum(map(len, sections)))
        sections.append(str(index).encode("ascii") + b" 0 obj\n" + obj + b"\nendobj\n")
    xref_at = sum(map(len, sections))
    sections.append(
        b"xref\n0 6\n0000000000 65535 f \n"
        + b"".join(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets[1:])
        + b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n"
        + str(xref_at).encode("ascii") + b"\n%%EOF\n"
    )
    return b"".join(sections)


_FIXTURE = _fictional_pdf()


class _FixtureOnlyScanner:
    """Never represent this allowlist test double as a malware scanner."""

    def scan(self, data):
        return type(data) is bytes and data == _FIXTURE


@lru_cache(maxsize=1)
def _local_backend():
    """Keep ephemeral encryption key and temporary root for this test process."""
    if LocalEncryptedClamdBackend is None:
        raise PrivateDocumentStorageError("fictional_storage_unavailable")
    temporary = tempfile.TemporaryDirectory(prefix="jireh-fictional-document-")
    backend = LocalEncryptedClamdBackend(
        root=temporary.name,
        encryption_key=secrets.token_bytes(32),
        scanner=_FixtureOnlyScanner(),
        max_bytes=len(_FIXTURE),
    )
    return temporary, backend


def _guard(request):
    if (
        getattr(settings, "JIREH_SYNTHETIC_DOCUMENTS_ONLY", False) is not True
        or settings.ROOT_URLCONF not in _ALLOWED_URLCONFS
    ):
        raise PermissionDenied("Fictional document workflow disabled.")
    if request.GET:
        raise ValueError("query_parameters_not_supported")


def _draft(request, school_id, household_id, academic_year_id):
    draft, _ = selected_student_ids_for_draft(
        user=request.user,
        school_id=school_id,
        household_id=household_id,
        academic_year_id=academic_year_id,
    )
    return draft


def _backend():
    return _local_backend()[1]


def _error(exc):
    if isinstance(exc, PermissionDenied):
        return JsonResponse({"detail": "Forbidden."}, status=403)
    if isinstance(exc, Http404):
        return JsonResponse({"detail": "Not found."}, status=404)
    if isinstance(exc, (PrivateDocumentStorageError, OSError)):
        return JsonResponse({"detail": "Fictional storage unavailable."}, status=503)
    if isinstance(exc, ValueError) and str(exc) == "query_parameters_not_supported":
        return JsonResponse({"detail": "Query parameters not accepted."}, status=400)
    return JsonResponse({"detail": "Fictional document unavailable."}, status=409)


def _body_key(request):
    if request.content_type != "application/json" or len(request.body) > 128:
        raise ValueError("invalid_body")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_key")
            result[key] = value
        return result

    body = json.loads(request.body.decode("utf-8"), object_pairs_hook=unique_object)
    if type(body) is not dict or set(body) != {"request_key"}:
        raise ValueError("invalid_body")
    key = body["request_key"]
    if type(key) is not str:
        raise ValueError("invalid_key")
    try:
        parsed = UUID(key)
    except (TypeError, AttributeError, ValueError):
        raise ValueError("invalid_key") from None
    if str(parsed) != key or parsed.version != 4 or parsed.int == 0:
        raise ValueError("invalid_key")
    return key


@never_cache
@require_GET
def list_fictional_documents(request, school_id, household_id, academic_year_id):
    """Read metadata only, after current family grant and DRAFT checks."""
    try:
        _guard(request)
        draft = _draft(request, school_id, household_id, academic_year_id)
        records = list(
            FinancialDocument.objects.for_school(draft.school_id)
            .filter(
                application=draft,
                household_id=draft.household_id,
                state=FinancialDocument.STATE_ACTIVE,
            )
            .order_by("version")
            .values("id", "version", "category", "byte_count")[:51]
        )
    except (PermissionDenied, Http404, ValueError) as exc:
        return _error(exc)
    return JsonResponse({
        "demo_only": True,
        "documents": [
            {
                "document_id": str(item["id"]), "version": item["version"],
                "category": item["category"], "byte_count": item["byte_count"],
            } for item in records[:50]
        ],
        "has_more": len(records) > 50,
    })


@never_cache
@csrf_protect
@require_POST
def create_fictional_document(request, school_id, household_id, academic_year_id):
    """Create an encrypted copy of the one server-owned fictional PDF."""
    try:
        _guard(request)
        _draft(request, school_id, household_id, academic_year_id)
        key = _body_key(request)
        record = create_synthetic_document(
            user=request.user, school_id=school_id, household_id=household_id,
            academic_year_id=academic_year_id, request_key=key,
            category="FICTIONAL_TAX", data=_FIXTURE, policy=_POLICY,
            backend=_backend(),
        )
    except (
        PermissionDenied, Http404, ValidationError, DocumentLifecycleError,
        PrivateDocumentStorageError, OSError,
    ) as exc:
        return _error(exc)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return JsonResponse({"detail": "Invalid fictional request."}, status=400)
    return JsonResponse({
        "demo_only": True, "document_id": str(record.pk),
        "version": record.version, "status": "FICTIONAL_DOCUMENT_ACTIVE",
    })


@never_cache
@require_GET
def read_fictional_document(
    request, school_id, household_id, academic_year_id, document_id,
):
    """Read only this household's authenticated, integrity-checked fixture."""
    try:
        _guard(request)
        _draft(request, school_id, household_id, academic_year_id)
        data = read_synthetic_document(
            user=request.user, school_id=school_id, household_id=household_id,
            academic_year_id=academic_year_id, document_id=document_id,
            backend=_backend(),
        )
    except (PermissionDenied, Http404, DocumentLifecycleError, PrivateDocumentStorageError, OSError, ValueError) as exc:
        return _error(exc)
    response = HttpResponse(data, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="fictional-sample.pdf"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


@never_cache
@csrf_protect
@require_http_methods(["DELETE"])
def remove_fictional_document(
    request, school_id, household_id, academic_year_id, document_id,
):
    """Commit an unreadable tombstone before deleting the encrypted fixture."""
    try:
        _guard(request)
        _draft(request, school_id, household_id, academic_year_id)
        if request.body:
            return JsonResponse({"detail": "No request body accepted."}, status=400)
        record = delete_synthetic_document(
            user=request.user, school_id=school_id, household_id=household_id,
            academic_year_id=academic_year_id, document_id=document_id,
            backend=_backend(),
        )
    except (PermissionDenied, Http404, DocumentLifecycleError, PrivateDocumentStorageError, OSError, ValueError) as exc:
        return _error(exc)
    return JsonResponse({
        "demo_only": True, "document_id": str(record.pk),
        "status": "FICTIONAL_DOCUMENT_DELETED",
    })
