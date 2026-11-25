"""Accept a reason-free confidential review request in the fictional workspace."""

from django.conf import settings
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from .models import FictionalContributorException


def contributor_review_pending(application_id):
    """Read a marker only after the caller has authorized the application."""
    return FictionalContributorException.objects.filter(application_id=application_id).exists()


def can_read_contributor_review(user):
    """Require an explicit grant in addition to the caller's school director check."""
    return (
        getattr(settings, "JIREH_SYNTHETIC_APPLICATION_REVIEW", False) is True
        and user.user_permissions.filter(
            content_type__app_label="schools", content_type__model="fictionalcontributorexception",
            codename="view_fictionalcontributorexception",
        ).exists()
    )


@require_POST
@csrf_protect
@transaction.atomic
def workspace_contributor_exception(request, school_id, household_id, academic_year_id):
    if (getattr(settings, "JIREH_SYNTHETIC_APPLICATION_REVIEW", False) is not True
            or getattr(settings, "JIREH_SYNTHETIC_SUBMISSION_ONLY", False) is not True):
        raise Http404("Fictional review unavailable.")
    if (request.GET or request.content_type != "application/x-www-form-urlencoded"
            or set(request.POST) - {"csrfmiddlewaretoken"}):
        return HttpResponse("Review request accepts no details.", status=400)

    # Reuse the draft and grant locking order used for encrypted questionnaire changes.
    from jireh.financial_aid.synthetic_questionnaire_storage import _locked_draft

    draft = _locked_draft(request.user, school_id, household_id, academic_year_id)
    FictionalContributorException.objects.get_or_create(
        application=draft, defaults={"requested_by": request.user},
    )
    return redirect("jireh_workspace_review", school_id, household_id, academic_year_id)
