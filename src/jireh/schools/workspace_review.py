"""Disposable family review page using saved, independently scoped records."""
import hmac

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_POST, require_http_methods

from jireh.financial_aid.document_lifecycle import DocumentLifecycleError
from jireh.financial_aid.models import (
    SYNTHETIC_HANDOFF_NOTICE_VERSION, SyntheticAidSubmission, SyntheticPrepaymentHandoff,
)
from jireh.financial_aid.questionnaire_validation import QuestionnaireValidationError
from jireh.financial_aid.synthetic_document_views import PrivateDocumentStorageError
from jireh.financial_aid.synthetic_submission import record_synthetic_demo_submission
from jireh.runtime.customer_financial_policy import financial_scope_allowed
from .customer_workspace import _page
from .fictional_need_decisions import fixture_matches
from .workspace_contributor_exception import contributor_review_pending


@ensure_csrf_cookie
@csrf_protect
@require_http_methods(["GET", "HEAD", "POST"])
def workspace_review(request, school_id, household_id, academic_year_id):
    # Keep the optional crypto dependency out of the basic workspace imports.
    try:
        from jireh.financial_aid.synthetic_application_review import (
            FictionalReviewError, confirm_fictional_application_review,
            read_fictional_application_review,
        )
        from jireh.financial_aid.synthetic_submission_preflight import (
            _submission_preflight_from_review,
        )
    except ImportError:
        return HttpResponse("Fictional review unavailable.", status=503)
    scope = dict(user=request.user, school_id=school_id, household_id=household_id,
                 academic_year_id=academic_year_id,
                 key=getattr(settings, "JIREH_SYNTHETIC_QUESTIONNAIRE_KEY", None))
    if request.GET:
        return HttpResponse("Query parameters not accepted.", status=400)
    try:
        if request.method == "POST":
            if (request.content_type != "application/x-www-form-urlencoded"
                    or set(request.POST) - {"csrfmiddlewaretoken", "state_digest", "reviewed"}
                    or len(request.POST.getlist("state_digest")) != 1
                    or request.POST.getlist("reviewed") != ["yes"]):
                return HttpResponse("Explicit fictional review required.", status=400)
            confirm_fictional_application_review(
                **scope, expected_digest=request.POST["state_digest"], reviewed=True,
            )
            return redirect("jireh_workspace_review", school_id, household_id, academic_year_id)
        state = read_fictional_application_review(**scope)
        preflight = _submission_preflight_from_review(state)
    except FictionalReviewError as exc:
        if str(exc) == "review_state_changed":
            return HttpResponse("Saved draft changed. Reload and review again.", status=409)
        if str(exc) in ("review_incomplete", "review_confirmation_required"):
            return HttpResponse("Fictional review requirements not satisfied.", status=400)
        return HttpResponse("Fictional review unavailable.", status=503)
    except (QuestionnaireValidationError, DocumentLifecycleError, PrivateDocumentStorageError, OSError):
        return HttpResponse("Fictional review unavailable.", status=503)
    draft = state["draft"]
    rehearsal_receipt = None
    if fixture_matches(school_id, academic_year_id, household_id):
        rehearsal_receipt = {
            "recorded": SyntheticAidSubmission.objects.filter(application=draft).exists(),
            "available": bool(state["confirmation"]) and not state["reasons"]
                         and not contributor_review_pending(draft.pk),
        }
    handoff = None
    if financial_scope_allowed(school_id, household_id, academic_year_id):
        available = (
            state["confirmation"] is not None and preflight.contributor_review_status != "pending"
        )
        handoff = {
            "notice_version": SYNTHETIC_HANDOFF_NOTICE_VERSION,
            "available": available,
            "current": available and SyntheticPrepaymentHandoff.objects.filter(
                confirmation=state["confirmation"],
            ).exists(),
        }
    response = _page(request, "review", household=draft.household,
                     year=draft.academic_year, review=state,
                     submission_preflight=preflight, rehearsal_receipt=rehearsal_receipt, handoff=handoff)
    response["Referrer-Policy"] = "same-origin"
    return response


@require_POST
@csrf_protect
@transaction.atomic
def workspace_rehearsal_receipt(request, school_id, household_id, academic_year_id):
    """Explicit fictional milestone only, never final paid submission or consent."""
    if not fixture_matches(school_id, academic_year_id, household_id):
        raise Http404("Fictional receipt unavailable.")
    if (request.GET or request.content_type != "application/x-www-form-urlencoded"
            or set(request.POST) - {"csrfmiddlewaretoken", "state_digest", "attested"}
            or request.POST.getlist("attested") != ["yes"]
            or len(request.POST.getlist("state_digest")) != 1):
        return HttpResponse("Explicit fictional receipt confirmation required.", status=400)
    try:
        from jireh.financial_aid.synthetic_application_review import (
            FictionalReviewError, read_fictional_application_review,
        )
    except ImportError:
        return HttpResponse("Fictional receipt unavailable.", status=503)
    try:
        state = read_fictional_application_review(
            user=request.user, school_id=school_id, household_id=household_id,
            academic_year_id=academic_year_id,
            key=getattr(settings, "JIREH_SYNTHETIC_QUESTIONNAIRE_KEY", None),
        )
        if (state["reasons"] or not state["confirmation"]
                or not hmac.compare_digest(state["digest"], request.POST["state_digest"])):
            return HttpResponse("Current fictional review required.", status=409)
        record_synthetic_demo_submission(
            user=request.user, school_id=school_id, household_id=household_id,
            academic_year_id=academic_year_id, accuracy_attested=True,
        )
    except (FictionalReviewError, ValidationError, QuestionnaireValidationError,
            DocumentLifecycleError, PrivateDocumentStorageError, OSError, TypeError):
        return HttpResponse("Fictional receipt unavailable.", status=409)
    return redirect("jireh_workspace_review", school_id, household_id, academic_year_id)


@require_POST
@csrf_protect
def workspace_prepayment_handoff(request, school_id, household_id, academic_year_id):
    """Hand off the currently confirmed fictional draft for director readback."""
    from jireh.financial_aid.synthetic_application_review import FictionalReviewError
    from jireh.financial_aid.synthetic_prepayment_handoff import record_prepayment_handoff

    if (request.GET or request.content_type != "application/x-www-form-urlencoded"
            or set(request.POST) - {"csrfmiddlewaretoken", "state_digest", "handed_off", "notice_version"}
            or request.POST.getlist("handed_off") != ["yes"]
            or request.POST.getlist("notice_version") != [SYNTHETIC_HANDOFF_NOTICE_VERSION]
            or len(request.POST.getlist("state_digest")) != 1):
        return HttpResponse("Explicit fictional handoff required.", status=400)
    try:
        record_prepayment_handoff(
            user=request.user, school_id=school_id, household_id=household_id,
            academic_year_id=academic_year_id, expected_digest=request.POST["state_digest"],
            notice_version=request.POST["notice_version"],
        )
    except (FictionalReviewError, QuestionnaireValidationError, DocumentLifecycleError,
            PrivateDocumentStorageError, OSError):
        return HttpResponse("Current fictional review required for handoff.", status=409)
    return redirect("jireh_workspace_review", school_id, household_id, academic_year_id)
