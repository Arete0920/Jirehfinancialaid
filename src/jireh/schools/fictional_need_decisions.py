"""Fictional director decision and readback, deliberately separate from actual awards.

Reuses CROWN's retry/financial invariants (test_recommend_award_retry_guard.py,
test_aid_award_invariants.py at 46b56609fe18360299b08eabaa8bccdffb356a0e)
without importing its ledger or policy. Only explicit disposable fixture scope.
"""
from uuid import UUID

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
from jireh.runtime.customer_financial_policy import financial_scope_allowed
from jireh.financial_aid.synthetic_questionnaire_preview import require_synthetic_questionnaire_preview
from .access import require_aid_director_access, require_household_access
from .grant_admin import _lock_authorized_school
from .models import AcademicYear, HouseholdAccess, School, SchoolStaffAccess
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


def _current_rehearsal_receipt(draft, questionnaire_revision):
    receipt = SyntheticAidSubmission.objects.filter(
        application=draft, accuracy_attested=True, consent_version=SYNTHETIC_DISCLOSURE_VERSION,
    ).first()
    if receipt is None or not HouseholdAccess.objects.filter(
        household_id=draft.household_id, user_id=receipt.actor_user_id, user__is_active=True, is_active=True,
    ).exists():
        raise ValidationError("Fictional decision unavailable.")
    # A fictional receipt is historical. Require the receipt actor's current
    # revision-bound review before recording or replaying a need decision.
    try:
        from jireh.financial_aid.document_lifecycle import DocumentLifecycleError
        from jireh.financial_aid.questionnaire_validation import QuestionnaireValidationError
        from jireh.financial_aid.synthetic_application_review import (
            FictionalReviewError, read_fictional_application_review,
        )
        from jireh.financial_aid.synthetic_document_views import PrivateDocumentStorageError
    except ImportError as exc:
        raise ValidationError("Fictional decision unavailable.") from exc
    try:
        review = read_fictional_application_review(
            user=receipt.actor_user, school_id=draft.school_id, household_id=draft.household_id,
            academic_year_id=draft.academic_year_id, key=getattr(settings, "JIREH_SYNTHETIC_QUESTIONNAIRE_KEY", None),
        )
    except (FictionalReviewError, DocumentLifecycleError, QuestionnaireValidationError,
            PrivateDocumentStorageError, PermissionDenied, Http404, OSError) as exc:
        raise ValidationError("Fictional decision unavailable.") from exc
    if (review["draft"].pk != draft.pk or review["revision"] != questionnaire_revision
            or review["reasons"] or review["confirmation"] is None
            or review["confirmation"].questionnaire_revision != questionnaire_revision):
        raise ValidationError("Fictional decision unavailable.")
    return receipt


@transaction.atomic
def record_fictional_need_decision(
    *, user, school_id, year_id, application_id, expected_revision,
    questionnaire_revision, plan_revision, amount_cents, handoff_id=None,
):
    """Append one current decision, or return an exact retry without duplication."""
    fixture_scope = None
    if handoff_id is None:
        require_synthetic_questionnaire_preview()
        if not fixture_matches(school_id, year_id):
            raise Http404("Fictional decision unavailable.")
    else:
        fixture = getattr(settings, "JIREH_SAVED_NEED_FIXTURE", None)
        if (type(handoff_id) is not UUID or not handoff_id.int or type(fixture) is not SavedNeedFixture
                or (fixture.school_id, fixture.academic_year_id) != (school_id, year_id)
                or not financial_scope_allowed(school_id, fixture.household_id, year_id)):
            raise Http404("Fictional decision unavailable.")
        fixture_scope = (school_id, fixture.household_id, year_id)
    school = _lock_authorized_school(actor=user, school_id=school_id)
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
    receipt = handoff = None
    if handoff_id is None:
        receipt = _current_rehearsal_receipt(draft, questionnaire_revision)
    else:
        from jireh.financial_aid.synthetic_prepayment_handoff import current_prepayment_handoff

        handoff = current_prepayment_handoff(draft, questionnaire_revision, handoff_id=handoff_id)
        if handoff is None:
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
        scenario_committed_aid_cents=other, scenario_proposed_aid_cents=amount_cents, fixture_scope=fixture_scope,
    )
    if not preview or preview["status"] != "available":
        raise ValidationError("Fictional decision unavailable.")
    if replay:
        if (latest.questionnaire_id != preview["questionnaire_id"] or latest.plan_id != preview["plan_id"]
                or latest.receipt_id != (receipt.pk if receipt else None)
                or latest.handoff_id != (handoff.pk if handoff else None)
                or latest.need_cents != preview["unmet_tuition_cents"]
                or latest.dataset_sha256 != preview["dataset_sha256"]
                or latest.calculation_version != preview["calculation_version"]):
            raise ValidationError("Fictional decision unavailable.")
        return latest
    return FictionalNeedDecision.objects.create(
        application=draft, questionnaire_id=preview["questionnaire_id"],
        questionnaire_revision=questionnaire_revision, plan_id=preview["plan_id"],
        receipt=receipt, handoff=handoff, actor_user=user, revision=actual_revision+1, amount_cents=amount_cents,
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
    return decision_budget_for_plan(plan)


def decision_budget_for_plan(plan):
    """Reconcile the latest journal entries against an already authorized plan."""
    allocated = _current(plan.school_id, plan.academic_year_id).aggregate(total=Sum("amount_cents"))["total"] or 0
    remaining = plan.as_plan().annual_aid_budget_cents - allocated
    return {"allocated_cents": allocated, "remaining_cents": remaining,
            "overallocated": remaining < 0, "plan_revision": plan.revision}


def read_family_decision(*, user, school_id, household_id, year_id):
    household = require_household_access(user, school_id=school_id, household_id=household_id)
    if not fixture_matches(household.school_id, year_id, household.pk):
        return None
    require_synthetic_questionnaire_preview()
    row = _current(household.school_id, year_id).filter(
        application__household_id=household.pk, receipt__isnull=False,
    ).values("revision", "amount_cents").first()
    return row

@transaction.atomic
def read_signed_family_decision(*, user, school_id, household_id, year_id):
    if not financial_scope_allowed(school_id, household_id, year_id):
        return None
    require_household_access(user, school_id=school_id, household_id=household_id)
    if not School.objects.select_for_update().filter(pk=school_id, is_active=True).exists():
        raise Http404()
    require_household_access(user, school_id=school_id, household_id=household_id)
    row = _current(school_id, year_id).filter(
        application__household_id=household_id, application__status=AidApplication.STATUS_DRAFT,
        handoff__confirmation__actor_user_id=user.pk,
    ).select_related("application").first()
    if row is None:
        return None
    from jireh.financial_aid.synthetic_prepayment_handoff import current_prepayment_handoff

    if current_prepayment_handoff(
        row.application, row.questionnaire_revision, handoff_id=row.handoff_id,
    ) is None:
        return None
    return {"revision": row.revision, "amount_cents": row.amount_cents}
