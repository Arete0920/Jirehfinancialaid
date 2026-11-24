"""Disposable family review page using saved, independently scoped records."""
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from jireh.financial_aid.document_lifecycle import DocumentLifecycleError
from jireh.financial_aid.questionnaire_validation import QuestionnaireValidationError
from jireh.financial_aid.synthetic_document_views import PrivateDocumentStorageError
from .customer_workspace import _page


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
    except FictionalReviewError as exc:
        if str(exc) == "review_state_changed":
            return HttpResponse("Saved draft changed. Reload and review again.", status=409)
        if str(exc) in ("review_incomplete", "review_confirmation_required"):
            return HttpResponse("Fictional review requirements not satisfied.", status=400)
        return HttpResponse("Fictional review unavailable.", status=503)
    except (QuestionnaireValidationError, DocumentLifecycleError, PrivateDocumentStorageError, OSError):
        return HttpResponse("Fictional review unavailable.", status=503)
    draft = state["draft"]
    response = _page(request, "review", household=draft.household,
                     year=draft.academic_year, review=state)
    response["Referrer-Policy"] = "same-origin"
    return response
