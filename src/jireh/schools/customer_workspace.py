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
import re
import secrets
from decimal import Decimal
from functools import wraps
from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponseForbidden, HttpResponseNotFound, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST, require_safe

from jireh.financial_aid.family_views import family_annual_draft
from jireh.financial_aid.student_views import selected_students
from jireh.financial_aid.views import (
    staff_application_detail, staff_application_index, staff_draft_workload,
)
from jireh.financial_aid.fictional_assessment_metadata import read_fictional_assessment_metadata
from jireh.financial_aid.questionnaire_validation import QuestionnaireValidationError
from jireh.financial_aid.synthetic_demo_views import record_synthetic_staff_offer
from jireh.financial_aid.synthetic_offers import read_synthetic_director_offer
from jireh.financial_aid.workload import WorkloadIntegrityError
from .access import require_aid_director_access, require_household_access
from .demo_director_summary import _summary
from .demo_seed import DEMO_SCHOOL_A_CODE, DEMO_SCHOOL_B_CODE
from .models import AcademicYear, FictionalContributorDecision, HouseholdAccess, SchoolStaffAccess
from .views import household_students
from .workspace_contributor_exception import can_read_contributor_review, contributor_review_pending
from .saved_need_workspace import read_saved_need_preview
from .fictional_income_reviews import read_income_evidence, record_income_evidence
from .enrollment_preview_workspace import read_fictional_enrollment_case
from .fictional_need_decisions import (
    read_decision_budget, read_director_decisions, read_family_decision, record_fictional_need_decision,
)


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
        "local_presenter": (os.environ.get("DJANGO_SETTINGS_MODULE") == _DEMO_MODULE
                            and settings.ROOT_URLCONF == "jireh.schools.demo_urls"),
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
    family_decision = read_family_decision(
        user=request.user, school_id=school_id, household_id=household_id, year_id=academic_year_id,
    ) if draft else None
    if family_decision:
        family_decision["dollars"] = _dollars(family_decision.pop("amount_cents"))
    return _page(
        request, "family", household=household, year=year,
        draft=draft, children=children, selected_count=len(ids), family_decision=family_decision,
        questionnaire_enabled=getattr(settings, "JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE", False) is True,
        documents_enabled=getattr(settings, "JIREH_SYNTHETIC_DOCUMENTS_ONLY", False) is True,
        review_enabled=getattr(settings, "JIREH_SYNTHETIC_APPLICATION_REVIEW", False) is True,
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
    fictional_summary = None
    if _fictional_director_mode(school, allow_control_school=True):
        try:
            fictional_summary = _summary(school, year)
        except WorkloadIntegrityError:
            return HttpResponse("Director summary unavailable.", status=503)
        # Reuse the CROWN-derived validated read model, rather than running
        # a second workload aggregation for the same school and year.
        workload = {
            "draft_application_records": fictional_summary["draft_applications"],
            "distinct_draft_households": fictional_summary["draft_households"],
            "selected_household_student_links": fictional_summary["selected_household_child_links"],
        }
        fictional_summary["offer_face_value_dollars"] = _dollars(
            fictional_summary["fictional_offer_face_value_cents"],
        )
    else:
        workload_response = staff_draft_workload(request, school_id, academic_year_id)
        workload = _read_json(workload_response)
        if workload is None:
            return workload_response
    decision_budget = read_decision_budget(user=request.user, school_id=school.pk, year_id=year.pk)
    if decision_budget:
        for name in ("allocated", "remaining"):
            decision_budget[name] = _dollars(decision_budget.pop(name + "_cents"))
    return _page(
        request, "director", school=school, year=year,
        inventory=inventory, workload=workload, fictional_summary=fictional_summary,
        decision_budget=decision_budget,
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
    rehearsal = None
    if _fictional_director_mode(school):
        try:
            rehearsal = _director_rehearsal(
                request.user, school, year, application_id, case,
            )
        except (QuestionnaireValidationError, OSError, ValueError):
            return HttpResponse("Fictional director evidence unavailable.", status=503)
    held = contributor_review_pending(application_id)
    can_review = can_read_contributor_review(request.user)
    contributor_decision = None
    if can_review and not held:
        contributor_decision = FictionalContributorDecision.objects.filter(marker__application_id=application_id).first()
    response = _page(request, "case", school=school, year=year, case=case, rehearsal=rehearsal,
                     contributor_review_pending=held and can_review, fictional_offer_held=held,
                     contributor_decision=contributor_decision)
    # Native same-origin POST forms need an origin/referrer for Django CSRF.
    # Retain no-referrer for pages without these forms and suppress cross-origin
    # referrers even when a projection or contributor decision is available.
    saved_need = rehearsal.get("saved_need") if rehearsal else None
    if (held and can_review) or (saved_need and saved_need["status"] == "available"):
        response["Referrer-Policy"] = "same-origin"
    return response


def _dollars(cents):
    return f"{Decimal(cents) / 100:,.2f}"


def _fictional_director_mode(school, *, allow_control_school=False):
    codes = (DEMO_SCHOOL_A_CODE, DEMO_SCHOOL_B_CODE) if allow_control_school else (DEMO_SCHOOL_A_CODE,)
    return (
        school.code in codes
        and getattr(settings, "JIREH_SYNTHETIC_SUBMISSION_ONLY", False) is True
    )


def _director_rehearsal(user, school, year, application_id, case):
    scope = dict(user=user, school_id=school.pk, academic_year_id=year.pk,
                 application_id=application_id)
    metadata = read_fictional_assessment_metadata(**scope)
    if len(case["selected_student_ids"]) > _SCOPE_LIMIT:
        raise ValueError("Fictional case readback unavailable.")
    offers = []
    for student_id in case["selected_student_ids"]:
        if not metadata.has_fictional_receipt:
            break
        try:
            saved = read_synthetic_director_offer(**scope, student_id=student_id)
        except Http404:
            saved = None
        if saved is not None:
            offers.append({"student_id": student_id, "dollars": _dollars(saved.amount_cents)})
        else:
            offers.append({"student_id": student_id, "dollars": None})
    # Recheck current school authorization after readback. No encrypted
    # questionnaire or document contents are returned to the director.
    saved_need = read_saved_need_preview(
        user=user, school=school, year=year, application_id=application_id,
        questionnaire_revision=metadata.questionnaire_revision,
    )
    enrollment = read_fictional_enrollment_case(
        user=user, school=school, year=year, application_id=application_id,
        selected_student_ids=case["selected_student_ids"],
    )
    if enrollment and enrollment["state"] == "available":
        for name in ("maximum", "pool", "cap"):
            enrollment[name] = _dollars(enrollment.pop(name + "_cents"))
    income_evidence = read_income_evidence(
        user=user, school=school, year=year, application_id=application_id, baseline=saved_need,
    )
    if income_evidence:
        amounts = ("annual_income",) if income_evidence.get("can_record") else ("baseline", "adjusted")
        for name in amounts:
            income_evidence[name] = _dollars(income_evidence.pop(name + "_cents"))
    if saved_need is not None and saved_need["status"] == "available":
        for name in ("net_tuition", "allowance", "contribution", "unmet_tuition"):
            saved_need[name] = _dollars(saved_need.pop(name + "_cents"))
    journal = read_director_decisions(user=user, school_id=school.pk, year_id=year.pk,
                                      application_id=application_id)
    if journal is not None:
        journal["history"] = [
            {"revision": row.revision, "dollars": _dollars(row.amount_cents),
             "questionnaire_revision": row.questionnaire_revision, "plan_revision": row.plan.revision,
             "actor": row.actor_user_id, "created_at": row.created_at}
            for row in journal["history"]
        ]
    require_aid_director_access(user, school_id=school.pk)
    return {
        "metadata": metadata,
        "saved_need": saved_need,
        "enrollment": enrollment,
        "income_evidence": income_evidence,
        "decision_journal": journal,
        "offers": offers,
    }


@require_POST
def workspace_case_offer(request, school_id, academic_year_id, application_id, student_id):
    """Reuse the same fixed fictional offer action; no new award contract."""
    school = require_aid_director_access(request.user, school_id=school_id)
    if not _fictional_director_mode(school):
        return HttpResponseNotFound()
    return record_synthetic_staff_offer(
        request, school_id, academic_year_id, application_id, student_id,
    )


_PROJECTION_MONEY = re.compile(r"[0-9]{1,8}(?:\.[0-9]{1,2})?")
_PROJECTION_REVISION = re.compile(r"[1-9][0-9]{0,8}")


@require_POST
@csrf_protect
def workspace_case_projection(request, school_id, academic_year_id, application_id):
    """Recalculate a need-only fictional proposal on the exact current evidence.

    Never persist a proposal, reserve school funds, create a receipt or award,
    or treat the entered committed amount as an actual ledger balance.
    """
    school = require_aid_director_access(request.user, school_id=school_id)
    year = get_object_or_404(AcademicYear.objects.for_school(school_id), pk=academic_year_id)
    if not _fictional_director_mode(school):
        raise Http404("Fictional projection unavailable.")
    fields = {"questionnaire_revision", "plan_revision", "committed", "proposed"}
    allowed = fields | {"csrfmiddlewaretoken"}
    if (request.GET or set(request.POST) - allowed or not fields <= set(request.POST)
            or any(len(request.POST.getlist(name)) != 1 for name in request.POST)
            or request.FILES
            or any(_PROJECTION_REVISION.fullmatch(request.POST[name]) is None
                   for name in ("questionnaire_revision", "plan_revision"))
            or any(_PROJECTION_MONEY.fullmatch(request.POST[name]) is None
                   for name in ("committed", "proposed"))):
        return HttpResponse("Invalid fictional projection.", status=400)
    projection = read_saved_need_preview(
        user=request.user, school=school, year=year, application_id=application_id,
        questionnaire_revision=int(request.POST["questionnaire_revision"]),
        expected_plan_revision=int(request.POST["plan_revision"]),
        scenario_committed_aid_cents=int(Decimal(request.POST["committed"]) * 100),
        scenario_proposed_aid_cents=int(Decimal(request.POST["proposed"]) * 100),
    )
    if projection is None:
        raise Http404("Fictional projection unavailable.")
    if projection["status"] != "available":
        response = _page(request, "need_projection", school=school, year=year,
                         application_id=application_id, projection=None)
        response.status_code = 409
        return response
    facts = projection["projection"]
    amounts = {name.removesuffix("_cents"): _dollars(cents) for name, cents in facts.items()}
    return _page(
        request, "need_projection", school=school, year=year, application_id=application_id,
        projection=amounts, questionnaire_revision=projection["questionnaire_revision"],
        plan_revision=projection["plan_revision"],
        unmet_tuition=_dollars(projection["unmet_tuition_cents"]),
    )


@require_POST
@csrf_protect
def workspace_income_evidence(request, school_id, academic_year_id, application_id):
    revisions = {"questionnaire_revision", "plan_revision"}
    fields = revisions | {"confirmed", "evidence_id"}
    if (request.GET or request.content_type != "application/x-www-form-urlencoded"
            or set(request.POST) - fields - {"csrfmiddlewaretoken"}
            or not fields <= set(request.POST)
            or any(len(request.POST.getlist(name)) != 1 for name in request.POST)
            or request.POST["confirmed"] != "yes"
            or any(_PROJECTION_REVISION.fullmatch(request.POST[name]) is None for name in revisions)):
        return HttpResponse("Invalid fictional income evidence review.", status=400)
    try:
        evidence_id = UUID(request.POST["evidence_id"])
    except ValueError:
        return HttpResponse("Invalid fictional income evidence review.", status=400)
    if str(evidence_id) != request.POST["evidence_id"]:
        return HttpResponse("Invalid fictional income evidence review.", status=400)
    try:
        record_income_evidence(
            user=request.user, school_id=school_id, year_id=academic_year_id, application_id=application_id,
            questionnaire_revision=int(request.POST["questionnaire_revision"]),
            plan_revision=int(request.POST["plan_revision"]), evidence_id=evidence_id,
        )
    except ValidationError:
        return HttpResponse("Fictional income evidence unavailable. Reload the case.", status=409)
    return redirect("jireh_workspace_case", school_id, academic_year_id, application_id)


@require_POST
@csrf_protect
def workspace_need_decision(request, school_id, academic_year_id, application_id, *, signed=False):
    fields = {"decision_revision", "questionnaire_revision", "plan_revision", "amount", "confirmed"}
    if signed:
        fields.add("handoff")
    if (request.GET or request.content_type != "application/x-www-form-urlencoded"
            or set(request.POST) - fields - {"csrfmiddlewaretoken"}
            or not fields <= set(request.POST)
            or any(len(request.POST.getlist(name)) != 1 for name in request.POST)
            or request.POST["confirmed"] != "yes"
            or re.fullmatch(r"0|[1-9][0-9]{0,8}", request.POST["decision_revision"]) is None
            or any(_PROJECTION_REVISION.fullmatch(request.POST[name]) is None
                   for name in ("questionnaire_revision", "plan_revision"))
            or _PROJECTION_MONEY.fullmatch(request.POST["amount"]) is None):
        return HttpResponse("Invalid fictional decision.", status=400)
    try:
        handoff_id = UUID(request.POST["handoff"]) if signed else None
    except ValueError:
        return HttpResponse("Invalid fictional handoff.", status=400)
    try:
        record_fictional_need_decision(
            user=request.user, school_id=school_id, year_id=academic_year_id,
            application_id=application_id, expected_revision=int(request.POST["decision_revision"]),
            questionnaire_revision=int(request.POST["questionnaire_revision"]),
            plan_revision=int(request.POST["plan_revision"]),
            amount_cents=int(Decimal(request.POST["amount"])*100), handoff_id=handoff_id,
        )
    except ValidationError:
        return HttpResponse("Fictional decision unavailable. Reload the case.", status=409)
    return redirect("jireh_workspace_case", school_id, academic_year_id, application_id)
