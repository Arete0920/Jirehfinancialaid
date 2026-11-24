"""Read-only platform-operations preview for the disposable local demonstration.

Never a school-creation, tenant-provisioning, SIS configuration, payment,
privileged bootstrap, or production API. Only synthetic school metadata.
"""
import secrets

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .demo_seed import DEMO_OPERATOR, DEMO_SCHOOL_A_CODE, DEMO_SCHOOL_B_CODE
from .models import AcademicYear, School, SchoolStaffAccess


class OperationsPreviewIntegrityError(RuntimeError):
    """Saved synthetic school/year inventory is incomplete or ambiguous."""


def _authorized_operator(user):
    """Explicit local-fixture operator; staff alone never grants authority."""
    return (
        settings.ROOT_URLCONF == "jireh.schools.demo_urls"
        and getattr(settings, "JIREH_SYNTHETIC_SUBMISSION_ONLY", False) is True
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and getattr(user, "is_staff", False)
        and not getattr(user, "is_superuser", True)
        and getattr(user, "username", None) == DEMO_OPERATOR
    )


def _saved_school_inventory():
    """Count only expected fictional schools; no financial or family queries."""
    schools = list(School.objects.order_by("code").values(
        "id", "code", "name", "is_active"
    ))
    expected_codes = {DEMO_SCHOOL_A_CODE, DEMO_SCHOOL_B_CODE}
    if len(schools) != 2 or {row["code"] for row in schools} != expected_codes:
        raise OperationsPreviewIntegrityError("Expected fictional schools unavailable.")
    school_ids = [row["id"] for row in schools]
    years = list(AcademicYear.objects.filter(school_id__in=school_ids).values(
        "school_id", "name", "start_date", "end_date"
    ))
    if len(years) != 2 or any(
        sum(row["school_id"] == school["id"] for row in years) != 1
        for school in schools
    ):
        raise OperationsPreviewIntegrityError("Academic-year inventory unavailable.")
    granted = list(SchoolStaffAccess.objects.filter(
        school_id__in=school_ids,
        is_active=True,
        role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
    ).values("school_id", "user_id"))
    rows = []
    for school in schools:
        school_year = next(y for y in years if y["school_id"] == school["id"])
        count = sum(1 for grant in granted if grant["school_id"] == school["id"])
        rows.append({
            "name": school["name"],
            "code": school["code"],
            "active": school["is_active"],
            "academic_year": school_year["name"],
            "director_grants": count,
            "setup": "Fictional seed only",
            "integration": "Not configured",
        })
    return rows


@never_cache
@require_GET
def local_operations_preview(request):
    """Show school registry facts to the explicit fictional operator only."""
    if request.GET:
        return JsonResponse({"detail": "Query parameters are not accepted."}, status=400)
    if not _authorized_operator(request.user):
        return JsonResponse({"detail": "Forbidden."}, status=403)
    try:
        rows = _saved_school_inventory()
    except OperationsPreviewIntegrityError:
        return JsonResponse({"detail": "Operations preview unavailable."}, status=503)
    nonce = secrets.token_urlsafe(16)
    response = render(request, "jireh/demo_platform_operations.html", {
        "schools": rows, "csp_nonce": nonce,
    })
    response["Content-Security-Policy"] = (
        f"default-src 'none'; style-src 'nonce-{nonce}'; "
        "connect-src 'none'; form-action 'none'; base-uri 'none'; "
        "frame-ancestors 'none'"
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Frame-Options"] = "DENY"
    return response
