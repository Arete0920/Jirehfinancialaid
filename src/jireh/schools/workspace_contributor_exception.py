"""Accept a reason-free confidential review request in the fictional workspace."""

from django.conf import settings
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from jireh.financial_aid.models import AidApplication
from .access import require_aid_director_access
from .models import FictionalContributorDecision, FictionalContributorException, School, SchoolStaffAccess


def contributor_review_pending(application_id):
    """Read a marker only after the caller has authorized the application."""
    return FictionalContributorException.objects.filter(application_id=application_id, resolution__isnull=True).exists()


def contributor_review_status(application_id):
    """Expose only the stage to a caller that already authorized the draft."""
    marker = FictionalContributorException.objects.filter(application_id=application_id).values("resolution__pk").first()
    if marker is None:
        return None
    return "completed" if marker["resolution__pk"] is not None else "pending"


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


@require_POST
@csrf_protect
@transaction.atomic
def workspace_contributor_decision(request, school_id, academic_year_id, application_id):
    if getattr(settings, "JIREH_SYNTHETIC_SUBMISSION_ONLY", False) is not True:
        raise Http404("Fictional review unavailable.")
    school = require_aid_director_access(request.user, school_id=school_id)
    get_object_or_404(School.objects.select_for_update(), pk=school.pk, is_active=True)
    get_object_or_404(SchoolStaffAccess.objects.select_for_update(), school=school, user=request.user,
                      role=SchoolStaffAccess.ROLE_AID_DIRECTOR, is_active=True)
    if not can_read_contributor_review(request.user):
        raise Http404("Fictional review unavailable.")
    outcomes = request.POST.getlist("decision")
    if (request.GET or request.content_type != "application/x-www-form-urlencoded"
            or set(request.POST) - {"csrfmiddlewaretoken", "decision"}
            or len(outcomes) != 1 or outcomes[0] not in FictionalContributorDecision.Outcome.values):
        return HttpResponse("Choose a fictional contributor review decision.", status=400)

    draft = get_object_or_404(AidApplication.objects.for_school(school.pk).select_for_update(of=("self",)),
                              pk=application_id, academic_year_id=academic_year_id,
                              academic_year__school_id=school.pk, household__school_id=school.pk,
                              household__is_active=True, status=AidApplication.STATUS_DRAFT)
    marker = get_object_or_404(FictionalContributorException, application=draft)
    record, _ = FictionalContributorDecision.objects.get_or_create(
        marker=marker, defaults={"decided_by": request.user, "outcome": outcomes[0]},
    )
    if record.outcome != outcomes[0] or record.decided_by_id != request.user.pk:
        return HttpResponse("A fictional contributor review decision is already recorded.", status=409)
    return redirect("jireh_workspace_case", school_id, academic_year_id, application_id)
