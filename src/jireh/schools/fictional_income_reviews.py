"""Director acceptance of a server-supplied fictional income evidence scenario."""

from datetime import date
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404

from jireh.financial_aid.models import FictionalIncomeEvidenceReview
from .fictional_need_decisions import decision_authorized, fixture_matches
from .grant_admin import _lock_authorized_school
from .models import AcademicYear, SchoolStaffAccess
from .saved_need_workspace import read_saved_need_preview


# Version this identity when changing any of the seeded evidence below. The
# scenario calendar is fixed so an offline rehearsal remains reproducible.
FICTIONAL_INCOME_EVIDENCE_ID = UUID("6255463a-c364-4c88-a32f-7f4d4eb38fa1")
_OBSERVED_FROM = date(2026, 9, 30)
_OBSERVED_THROUGH = date(2026, 10, 15)
_ANNUAL_INCOME_CENTS = 3_000_000
_ASSESSMENT_DATE = date(2026, 11, 25)
_REASSESS_ON = date(2026, 12, 1)


def _scope(baseline):
    return {
        "questionnaire_id": baseline["questionnaire_id"],
        "questionnaire_revision": baseline["questionnaire_revision"],
        "plan_id": baseline["plan_id"],
        "evidence_id": FICTIONAL_INCOME_EVIDENCE_ID,
    }


def _adjusted_need(*, user, school, year, application_id, row):
    # The encrypted questionnaire implementation is optional for the base demo.
    from jireh.financial_aid.saved_fictional_need import FictionalChangedIncomeReview

    review = FictionalChangedIncomeReview(
        evidence_id=row.evidence_id, reviewed_by_id=row.actor_user_id,
        questionnaire_id=row.questionnaire_id, questionnaire_revision=row.questionnaire_revision,
        plan_id=row.plan_id, plan_revision=row.plan.revision,
        observed_from=_OBSERVED_FROM, observed_through=_OBSERVED_THROUGH,
        accepted_on=row.accepted_on, reassess_on=row.reassess_on,
        annual_income_cents=_ANNUAL_INCOME_CENTS, policy_version="fictional-job-loss-v1",
    )
    return read_saved_need_preview(
        user=user, school=school, year=year, application_id=application_id,
        questionnaire_revision=row.questionnaire_revision, expected_plan_revision=row.plan.revision,
        changed_income_review=review, assessment_date=_ASSESSMENT_DATE,
    )


def read_income_evidence(*, user, school, year, application_id, baseline):
    if (not baseline or baseline["status"] != "available"
            or not fixture_matches(school.pk, year.pk) or not decision_authorized(user)):
        return None
    row = FictionalIncomeEvidenceReview.objects.select_related("plan").filter(**_scope(baseline)).first()
    if row is None:
        return {
            "can_record": True, "evidence_id": FICTIONAL_INCOME_EVIDENCE_ID,
            "annual_income_cents": _ANNUAL_INCOME_CENTS,
            "observed_from": _OBSERVED_FROM, "observed_through": _OBSERVED_THROUGH,
        }
    if row.actor_user_id != user.pk:
        return None
    adjusted = _adjusted_need(user=user, school=school, year=year, application_id=application_id, row=row)
    if not adjusted or adjusted["status"] != "available":
        return None
    return {
        "baseline_cents": baseline["unmet_tuition_cents"],
        "adjusted_cents": adjusted["unmet_tuition_cents"],
        "accepted_on": row.accepted_on,
        "reassess_on": row.reassess_on,
    }


@transaction.atomic
def record_income_evidence(
    *, user, school_id, year_id, application_id, questionnaire_revision, plan_revision, evidence_id,
):
    school = _lock_authorized_school(actor=user, school_id=school_id)
    if not fixture_matches(school.pk, year_id):
        raise Http404("Fictional income evidence unavailable.")
    if not SchoolStaffAccess.objects.select_for_update(of=("self",)).filter(
        school=school, user=user, is_active=True, role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
    ).exists() or not get_user_model().objects.select_for_update().filter(
        pk=user.pk, is_active=True,
    ).exists() or not decision_authorized(user, lock=True):
        raise PermissionDenied("Fictional income evidence authority required.")
    if evidence_id != FICTIONAL_INCOME_EVIDENCE_ID:
        raise ValidationError("Fictional income evidence has changed.")
    year = get_object_or_404(AcademicYear.objects.for_school(school.pk), pk=year_id)
    baseline = read_saved_need_preview(
        user=user, school=school, year=year, application_id=application_id,
        questionnaire_revision=questionnaire_revision, expected_plan_revision=plan_revision,
    )
    if baseline is None:
        raise Http404("Fictional income evidence unavailable.")
    if baseline["status"] != "available":
        raise ValidationError("Fictional income evidence unavailable.")
    scope = _scope(baseline)
    row = FictionalIncomeEvidenceReview.objects.select_related("plan").filter(**scope).first()
    if row is None:
        row = FictionalIncomeEvidenceReview(
            **scope, actor_user=user, accepted_on=_ASSESSMENT_DATE, reassess_on=_REASSESS_ON,
        )
    if row.actor_user_id != user.pk:
        raise PermissionDenied("Fictional income evidence authority required.")
    adjusted = _adjusted_need(user=user, school=school, year=year, application_id=application_id, row=row)
    if not adjusted or adjusted["status"] != "available":
        raise ValidationError("Fictional income evidence unavailable.")
    if row._state.adding:
        row.save(force_insert=True)
