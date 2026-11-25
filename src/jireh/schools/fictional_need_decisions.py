"""Fictional director decision and readback, deliberately separate from actual awards.

Reuses CROWN's retry/financial invariants (test_recommend_award_retry_guard.py,
test_aid_award_invariants.py at 46b56609fe18360299b08eabaa8bccdffb356a0e)
without importing its ledger or policy. Only explicit disposable fixture scope.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import OuterRef, Subquery, Sum
from django.http import Http404

from jireh.financial_aid.models import (
    AidApplication, FictionalNeedDecision, SyntheticAidSubmission, SYNTHETIC_DISCLOSURE_VERSION,
)
from jireh.financial_aid.school_plan_revisions import read_fictional_school_plan
from jireh.financial_aid.synthetic_questionnaire_preview import require_synthetic_questionnaire_preview
from .access import require_aid_director_access, require_household_access
from .grant_admin import _lock_authorized_school
from .models import AcademicYear, HouseholdAccess, SchoolStaffAccess
from .saved_need_workspace import SavedNeedFixture, read_saved_need_preview


def fixture_matches(school_id, year_id, household_id=None):
    fixture = getattr(settings, "JIREH_SAVED_NEED_FIXTURE", None)
    return (
        type(fixture) is SavedNeedFixture
        and getattr(settings, "JIREH_CUSTOMER_WORKSPACE_ACCEPTANCE", False) is True
        and getattr(settings, "JIREH_SYNTHETIC_SUBMISSION_ONLY", False) is True
        and (fixture.school_id, fixture.academic_year_id) == (school_id, year_id)
        and (household_id is None or fixture.household_id == household_id)
    )


def decision_authorized(user, *, lock=False):
    grants = user.user_permissions.through.objects.filter(
        user_id=user.pk, permission__content_type__app_label="financial_aid",
        permission__content_type__model="fictionalneeddecision",
        permission__codename="add_fictionalneeddecision",
    )
    if lock:
        grants = grants.select_for_update(of=("self",))
    return grants.exists()


def _current(school_id, year_id):
    rows = FictionalNeedDecision.objects.filter(
        application__school_id=school_id, application__academic_year_id=year_id,
    )
    latest = rows.filter(application_id=OuterRef("application_id")).order_by("-revision").values("revision")[:1]
    return rows.filter(revision=Subquery(latest))


def _journal(draft):
    return FictionalNeedDecision.objects.filter(application=draft).select_related("plan").order_by("-revision")


@transaction.atomic
def record_fictional_need_decision(
    *, user, school_id, year_id, application_id, expected_revision,
    questionnaire_revision, plan_revision, amount_cents,
):
    """Append one current decision, or return an exact retry without duplication."""
    require_synthetic_questionnaire_preview()
    school = _lock_authorized_school(actor=user, school_id=school_id)
    if not fixture_matches(school.pk, year_id):
        raise Http404("Fictional decision unavailable.")
    if not SchoolStaffAccess.objects.select_for_update(of=("self",)).filter(
        school=school, user=user, is_active=True, role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
    ).exists() or not get_user_model().objects.select_for_update().filter(
        pk=user.pk, is_active=True,
    ).exists() or not decision_authorized(user, lock=True):
        raise PermissionDenied("Fictional decision authority required.")
    if (type(expected_revision) is not int or expected_revision < 0
            or any(type(value) is not int or value < 1 for value in (questionnaire_revision, plan_revision))
            or type(amount_cents) is not int or amount_cents < 0
            or (expected_revision == 0 and amount_cents == 0)):
        raise ValidationError("Fictional decision unavailable.")
    year = AcademicYear.objects.for_school(school.pk).select_for_update().filter(pk=year_id).first()
    if year is None:
        raise Http404("Fictional decision unavailable.")
    draft = AidApplication.objects.for_school(school.pk).select_for_update(of=("self",)).filter(
        pk=application_id, academic_year=year, household_id=settings.JIREH_SAVED_NEED_FIXTURE.household_id,
        household__is_active=True, status=AidApplication.STATUS_DRAFT,
    ).first()
    if draft is None:
        raise Http404("Fictional decision unavailable.")
    receipt = SyntheticAidSubmission.objects.filter(
        application=draft, accuracy_attested=True, consent_version=SYNTHETIC_DISCLOSURE_VERSION,
    ).first()
    if receipt is None or not HouseholdAccess.objects.filter(
        household_id=draft.household_id, user_id=receipt.actor_user_id, user__is_active=True, is_active=True,
    ).exists():
        raise ValidationError("Fictional decision unavailable.")
    latest = _journal(draft).first()
    actual_revision = latest.revision if latest else 0
    replay = actual_revision == expected_revision + 1 and latest is not None and (
        latest.actor_user_id == user.pk and latest.questionnaire_revision == questionnaire_revision
        and latest.plan.revision == plan_revision and latest.amount_cents == amount_cents
    )
    if not replay and actual_revision != expected_revision:
        raise ValidationError("Fictional decision unavailable.")
    other = _current(school.pk, year.pk).exclude(application=draft).aggregate(total=Sum("amount_cents"))["total"] or 0
    preview = read_saved_need_preview(
        user=user, school=school, year=year, application_id=draft.pk,
        questionnaire_revision=questionnaire_revision, expected_plan_revision=plan_revision,
        scenario_committed_aid_cents=other, scenario_proposed_aid_cents=amount_cents,
    )
    if not preview or preview["status"] != "available":
        raise ValidationError("Fictional decision unavailable.")
    if replay:
        if (latest.questionnaire_id != preview["questionnaire_id"] or latest.plan_id != preview["plan_id"]
                or latest.receipt_id != receipt.pk or latest.need_cents != preview["unmet_tuition_cents"]
                or latest.dataset_sha256 != preview["dataset_sha256"]
                or latest.calculation_version != preview["calculation_version"]):
            raise ValidationError("Fictional decision unavailable.")
        return latest
    return FictionalNeedDecision.objects.create(
        application=draft, questionnaire_id=preview["questionnaire_id"],
        questionnaire_revision=questionnaire_revision, plan_id=preview["plan_id"],
        receipt=receipt, actor_user=user, revision=actual_revision+1, amount_cents=amount_cents,
        need_cents=preview["unmet_tuition_cents"],
        remaining_budget_cents=preview["projection"]["remaining_budget_cents"],
        calculation_version=preview["calculation_version"], dataset_sha256=preview["dataset_sha256"],
    )


def read_director_decisions(*, user, school_id, year_id, application_id):
    school = require_aid_director_access(user, school_id=school_id)
    if not fixture_matches(school.pk, year_id) or not decision_authorized(user):
        return None
    require_synthetic_questionnaire_preview()
    draft = AidApplication.objects.for_school(school.pk).filter(
        pk=application_id, academic_year_id=year_id,
        household_id=settings.JIREH_SAVED_NEED_FIXTURE.household_id, household__is_active=True,
    ).first()
    if draft is None:
        return None
    rows = list(_journal(draft)[:21])
    return {
        "revision": rows[0].revision if rows else 0, "history": rows[:20],
        "more": len(rows)>20,
    }


def read_decision_budget(*, user, school_id, year_id):
    school = require_aid_director_access(user, school_id=school_id)
    if not fixture_matches(school.pk, year_id) or not decision_authorized(user):
        return None
    require_synthetic_questionnaire_preview()
    plan = read_fictional_school_plan(user=user, school_id=school.pk, academic_year_id=year_id)
    if plan is None:
        return None
    allocated = _current(school.pk, year_id).aggregate(total=Sum("amount_cents"))["total"] or 0
    remaining = plan.as_plan().annual_aid_budget_cents - allocated
    return {"allocated_cents": allocated, "remaining_cents": remaining,
            "overallocated": remaining < 0, "plan_revision": plan.revision}


def read_family_decision(*, user, school_id, household_id, year_id):
    household = require_household_access(user, school_id=school_id, household_id=household_id)
    if not fixture_matches(household.school_id, year_id, household.pk):
        return None
    require_synthetic_questionnaire_preview()
    row = _current(household.school_id, year_id).filter(
        application__household_id=household.pk,
    ).values("revision", "amount_cents").first()
    return row
