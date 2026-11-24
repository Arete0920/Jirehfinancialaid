"""Generic customer workspace acceptance adapter.

Reuse the existing authenticated, school-scoped HTTP handlers. The server
renders persisted readback, not client-reported success. Fictional financial
rows are accepted only under an explicit disposable questionnaire gate.
No fixture credentials, live collection, awards, provisioning or payment.
Only disposable tests and the explicitly loopback-only demo may route this
candidate. The closed standalone runtime never imports it.
"""

import json
import os
import secrets
from functools import wraps

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseForbidden, HttpResponseNotFound
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_safe

from jireh.financial_aid.family_views import family_annual_draft
from jireh.financial_aid.student_views import selected_students
from jireh.financial_aid.views import (
    staff_application_detail, staff_application_index, staff_draft_workload,
)
from .access import require_aid_director_access, require_household_access
from .models import AcademicYear, HouseholdAccess, SchoolStaffAccess
from .views import household_students


_TEST_MODULES = frozenset({
    "jireh.schools.test_settings", "jireh.schools.postgres_test_settings",
})
_DEMO_MODULE = "jireh.schools.demo_settings"
_SCOPE_LIMIT = 100


def acceptance_only(view):
    """Fail closed even if a route is accidentally imported elsewhere."""
    @never_cache
    @wraps(view)
    def guarded(request, *args, **kwargs):
        startup = os.environ.get("DJANGO_SETTINGS_MODULE")
        if (
            settings.SETTINGS_MODULE not in (None, startup)
            or getattr(settings, "JIREH_CUSTOMER_WORKSPACE_ACCEPTANCE", False) is not True
        ):
            return HttpResponseNotFound()
        if startup in _TEST_MODULES:
            if not request.is_secure():
                return HttpResponseNotFound()
        elif startup == _DEMO_MODULE:
            if (
                os.environ.get("JIREH_LOCAL_DEMO_ONLY") != "YES-SYNTHETIC-ONLY"
                or request.META.get("REMOTE_ADDR") not in ("127.0.0.1", "::1")
                or request.get_host() not in ("127.0.0.1:8765", "localhost:8765")
            ):
                return HttpResponseNotFound()
        else:
            return HttpResponseNotFound()
        try:
            response = view(request, *args, **kwargs)
        except PermissionDenied:
            response = HttpResponseForbidden()
        except Http404:
            response = HttpResponseNotFound()
        response["X-Content-Type-Options"] = "nosniff"
        response["X-Frame-Options"] = "DENY"
        response.setdefault("Referrer-Policy", "no-referrer")
        response["X-Robots-Tag"] = "noindex, nofollow"
        return response
    return guarded


def _page(request, mode, **context):
    nonce = secrets.token_urlsafe(24)
    response = render(request, "jireh/customer_workspace.html", {
        "mode": mode, "csp_nonce": nonce,
        "authenticated": request.user.is_authenticated and request.user.is_active,
        **context,
    })
    response["Content-Security-Policy"] = (
        f"default-src 'none'; style-src 'nonce-{nonce}'; "
        f"script-src 'nonce-{nonce}'; connect-src 'self'; "
        "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    )
    return response


def _read_json(response):
    """Adapt a previously authorized read response without duplicating queries."""
    return json.loads(response.content) if response.status_code == 200 else None


@ensure_csrf_cookie
@require_safe
def workspace_home(request):
    if not request.user.is_authenticated or not request.user.is_active:
        return _page(request, "login")
    families = list(HouseholdAccess.objects.filter(
        user_id=request.user.pk, is_active=True,
        household__is_active=True, household__school__is_active=True,
        household__school__academic_years__isnull=False,
    ).order_by(
        "household__school__name", "household__name",
        "-household__school__academic_years__start_date", "household_id",
        "household__school__academic_years__pk",
    ).values(
        "household_id", "household__name", "household__school_id",
        "household__school__name", "household__school__academic_years__pk",
        "household__school__academic_years__name",
    )[:_SCOPE_LIMIT + 1])
    directors = list(SchoolStaffAccess.objects.filter(
        user_id=request.user.pk, is_active=True, school__is_active=True,
        role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        school__academic_years__isnull=False,
    ).order_by(
        "school__name", "-school__academic_years__start_date",
        "school_id", "school__academic_years__pk",
    ).values(
        "school_id", "school__name", "school__academic_years__pk",
        "school__academic_years__name",
    )[:_SCOPE_LIMIT + 1])
    return _page(
        request, "home", families=families[:_SCOPE_LIMIT],
        directors=directors[:_SCOPE_LIMIT],
        scopes_truncated=len(families) > _SCOPE_LIMIT or len(directors) > _SCOPE_LIMIT,
    )


@ensure_csrf_cookie
@require_safe
def workspace_family(request, school_id, household_id, academic_year_id):
    household = require_household_access(
        request.user, school_id=school_id, household_id=household_id,
    )
    year = get_object_or_404(AcademicYear.objects.for_school(school_id), pk=academic_year_id)
    scope = dict(school_id=school_id, household_id=household_id,
                 academic_year_id=academic_year_id)
    draft_response = family_annual_draft(request, **scope)
    if draft_response.status_code not in (200, 404):
        return draft_response
    draft = _read_json(draft_response)
    students_response = household_students(request, school_id, household_id)
    students = _read_json(students_response)
    if students is None:
        return students_response
    ids = set()
    if draft is not None:
        selection_response = selected_students(request, **scope)
        selected = _read_json(selection_response)
        if selected is None:
            return selection_response
        if selected["application_id"] != draft["id"]:
            return HttpResponseNotFound()
        ids = set(selected["student_ids"])
    children = [
        {**student, "selected": student["id"] in ids}
        for student in students["students"]
    ]
    return _page(
        request, "family", household=household, year=year,
        draft=draft, children=children, selected_count=len(ids),
        questionnaire_enabled=getattr(settings, "JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE", False) is True,
        documents_enabled=getattr(settings, "JIREH_SYNTHETIC_DOCUMENTS_ONLY", False) is True,
    )


@ensure_csrf_cookie
@require_safe
def workspace_director(request, school_id, academic_year_id):
    school = require_aid_director_access(request.user, school_id=school_id)
    year = get_object_or_404(AcademicYear.objects.for_school(school_id), pk=academic_year_id)
    inventory_response = staff_application_index(request, school_id, academic_year_id)
    inventory = _read_json(inventory_response)
    if inventory is None:
        return inventory_response
    workload_response = staff_draft_workload(request, school_id, academic_year_id)
    workload = _read_json(workload_response)
    if workload is None:
        return workload_response
    return _page(
        request, "director", school=school, year=year,
        inventory=inventory, workload=workload,
    )


@ensure_csrf_cookie
@require_safe
def workspace_case(request, school_id, academic_year_id, application_id):
    school = require_aid_director_access(request.user, school_id=school_id)
    year = get_object_or_404(AcademicYear.objects.for_school(school_id), pk=academic_year_id)
    case_response = staff_application_detail(request, school_id, academic_year_id, application_id)
    case = _read_json(case_response)
    if case is None:
        return case_response
    return _page(request, "case", school=school, year=year, case=case)
