"""Disposable HTML adapter for the existing customer workflow, not live routing."""
import json
import secrets
from decimal import Decimal
from functools import wraps
from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.http import Http404, HttpResponse, HttpResponseNotFound, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_POST, require_safe

from jireh.financial_aid.family_views import family_annual_draft
from jireh.financial_aid.student_views import selected_students
from jireh.financial_aid.views import staff_application_detail, staff_application_index, staff_draft_workload
from jireh.schools.access import require_aid_director_access, require_household_access
from jireh.schools.models import AcademicYear, HouseholdAccess, SchoolStaffAccess
from jireh.schools.session_views import end_session
from jireh.schools.views import household_students
from .customer_director_sessions import (
    DIRECTOR_SESSION_KEY, _director_credentials, _pending, director_session_authorized,
    disposable_identity_context,
)
from .customer_family_sessions import FAMILY_SESSION_KEY, family_session_eligible
from .customer_onboarding import ONBOARDING_SESSION_KEY, first_household_eligible
from .customer_urls import customer_core_available
from .customer_financial_policy import financial_scope_allowed

_SCOPE_LIMIT = 100
_NIL = UUID(int=0)
_SECOND = UUID(int=1)


def portal_only(view):
    """No demo settings, unmarked identity, real runtime or insecure transport."""
    @never_cache
    @wraps(view)
    def guarded(request, *args, **kwargs):
        if (not disposable_identity_context() or not customer_core_available(request)
                or getattr(settings, "JIREH_CUSTOMER_PORTAL_ACCEPTANCE", False) is not True):
            response = HttpResponseNotFound()
        else:
            try:
                response = view(request, *args, **kwargs)
            except PermissionDenied:
                response = HttpResponseForbidden()
            except Http404:
                response = HttpResponseNotFound()
            except DatabaseError:
                response = HttpResponse("Service unavailable.", status=503)
        response["X-Content-Type-Options"] = "nosniff"
        response["X-Frame-Options"] = "DENY"
        response.setdefault("Referrer-Policy", "no-referrer")
        response["X-Robots-Tag"] = "noindex, nofollow"
        return response
    return guarded


def _page(request, mode, **context):
    nonce = secrets.token_urlsafe(24)
    template = "jireh/customer_portal_auth.html" if mode == "auth" else "jireh/customer_workspace.html"
    response = render(request, template, {
        "mode": mode, "csp_nonce": nonce, "authenticated": request.user.is_authenticated,
        "nil_school": _NIL, "nil_household": _SECOND, **context,
    })
    response["Content-Security-Policy"] = (
        f"default-src 'none'; style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; "
        "connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    )
    return response


def _family_allowed(request):
    return (
        request.user.is_authenticated and request.session.get(FAMILY_SESSION_KEY) is True
        and DIRECTOR_SESSION_KEY not in request.session and ONBOARDING_SESSION_KEY not in request.session
        and getattr(settings, "JIREH_CUSTOMER_FAMILY_SESSION_ACCEPTANCE", False) is True
        and family_session_eligible(request.user)
    )


def _director_allowed(request, school_id):
    return (
        request.user.is_authenticated and FAMILY_SESSION_KEY not in request.session
        and ONBOARDING_SESSION_KEY not in request.session
        and director_session_authorized(request, school_id)
    )


def _auth(request, **context):
    return _page(request, "auth", **context)


@ensure_csrf_cookie
@require_safe
def portal_home(request):
    if _family_allowed(request):
        rows = list(HouseholdAccess.objects.filter(
            user_id=request.user.pk, is_active=True, household__is_active=True,
            household__school__is_active=True, household__school__academic_years__isnull=False,
        ).order_by("household__school__name", "household__name", "household_id",
                   "-household__school__academic_years__start_date", "household__school__academic_years__pk").values(
            "household_id", "household__name", "household__school_id", "household__school__name",
            "household__school__academic_years__pk", "household__school__academic_years__name",
        )[:_SCOPE_LIMIT + 1])
        return _page(request, "home", families=rows[:_SCOPE_LIMIT], scopes_truncated=len(rows) > _SCOPE_LIMIT)
    marker = request.session.get(DIRECTOR_SESSION_KEY)
    if isinstance(marker, dict) and request.user.is_authenticated:
        try:
            school_id = UUID(marker.get("school", ""))
        except (TypeError, ValueError, AttributeError):
            return _auth(request)
        if _director_allowed(request, school_id):
            rows = list(SchoolStaffAccess.objects.filter(
                user_id=request.user.pk, school_id=school_id, is_active=True, school__is_active=True,
                role=SchoolStaffAccess.ROLE_AID_DIRECTOR, school__academic_years__isnull=False,
            ).order_by("-school__academic_years__start_date", "school__academic_years__pk").values(
                "school_id", "school__name", "school__academic_years__pk", "school__academic_years__name",
            )[:_SCOPE_LIMIT + 1])
            return _page(request, "home", directors=rows[:_SCOPE_LIMIT], scopes_truncated=len(rows) > _SCOPE_LIMIT)
        if FAMILY_SESSION_KEY not in request.session and ONBOARDING_SESSION_KEY not in request.session:
            from .customer_director_sessions import director_session_available
            if director_session_available(request):
                try:
                    _pending(request, school_id)
                except PermissionDenied:
                    return _auth(request)
                refs = list(_director_credentials(request.user, school_id).order_by("pk").values_list(
                    "credential_id_digest", flat=True,
                )[:21])
                if 0 < len(refs) <= 20:
                    return _auth(request, pending_school=school_id, credential_refs=refs)
    if (request.user.is_authenticated and request.session.get(ONBOARDING_SESSION_KEY) is True
            and FAMILY_SESSION_KEY not in request.session and DIRECTOR_SESSION_KEY not in request.session
            and getattr(settings, "JIREH_CUSTOMER_FAMILY_SESSION_ACCEPTANCE", False) is True
            and getattr(settings, "JIREH_CUSTOMER_ONBOARDING_ACCEPTANCE", False) is True
            and first_household_eligible(request.user)):
        return _auth(request, redeem=True)
    return _auth(request)


@csrf_protect
@require_POST
def portal_logout(request):
    if not request.user.is_authenticated:
        raise PermissionDenied()
    return end_session(request)


@ensure_csrf_cookie
@require_safe
def portal_family(request, school_id, household_id, academic_year_id):
    if not _family_allowed(request):
        raise PermissionDenied()
    household = require_household_access(request.user, school_id=school_id, household_id=household_id)
    year = get_object_or_404(AcademicYear.objects.for_school(school_id), pk=academic_year_id)
    scope = dict(school_id=school_id, household_id=household_id, academic_year_id=academic_year_id)
    draft_response = family_annual_draft(request, **scope)
    if draft_response.status_code not in (200, 404):
        return draft_response
    draft = json.loads(draft_response.content) if draft_response.status_code == 200 else None
    students = household_students(request, school_id, household_id)
    if students.status_code != 200:
        return students
    ids = set()
    if draft is not None:
        selection = selected_students(request, **scope)
        if selection.status_code != 200:
            return selection
        selected = json.loads(selection.content)
        if selected["application_id"] != draft["id"]:
            raise Http404()
        ids = set(selected["student_ids"])
    children = [{**student, "selected": student["id"] in ids} for student in json.loads(students.content)["students"]]
    financial = financial_scope_allowed(school_id, household_id, academic_year_id)
    return _page(request, "family", household=household, year=year, draft=draft,
                 children=children, selected_count=len(ids), questionnaire_enabled=financial,
                 documents_enabled=financial, review_enabled=financial)


@ensure_csrf_cookie
@require_safe
def portal_director(request, school_id, academic_year_id):
    if not _director_allowed(request, school_id):
        raise PermissionDenied()
    school = require_aid_director_access(request.user, school_id=school_id)
    year = get_object_or_404(AcademicYear.objects.for_school(school_id), pk=academic_year_id)
    inventory = staff_application_index(request, school_id, academic_year_id)
    if inventory.status_code != 200:
        return inventory
    workload = staff_draft_workload(request, school_id, academic_year_id)
    if workload.status_code != 200:
        return workload
    return _page(request, "director", school=school, year=year,
                 inventory=json.loads(inventory.content), workload=json.loads(workload.content))


@ensure_csrf_cookie
@require_safe
def portal_case(request, school_id, academic_year_id, application_id):
    if not _director_allowed(request, school_id):
        raise PermissionDenied()
    school = require_aid_director_access(request.user, school_id=school_id)
    year = get_object_or_404(AcademicYear.objects.for_school(school_id), pk=academic_year_id)
    result = staff_application_detail(request, school_id, academic_year_id, application_id)
    if result.status_code != 200:
        return result
    case = json.loads(result.content)
    evidence = case.get("financial_evidence")
    need_amounts = {}
    if evidence and evidence["need"]["status"] == "available":
        need = evidence["need"]
        need_amounts = {
            label: f"${Decimal(need[field]) / 100:,.2f}"
            for field, label in (
                ("net_tuition_cents", "Net tuition after sibling discount"),
                ("allowance_cents", "Fictional regional living allowance"),
                ("contribution_cents", "Calculated household contribution"),
                ("unmet_tuition_cents", "Calculated unmet tuition"),
            )
        }
    return _page(request, "case", school=school, year=year, case=case, need_amounts=need_amounts)
