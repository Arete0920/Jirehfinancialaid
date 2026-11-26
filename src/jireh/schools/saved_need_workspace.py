"""Read-only aggregate saved-need presentation for one explicitly seeded demo case."""
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from jireh.financial_aid.annual_school_plan import FICTIONAL_15145_PLAN, AnnualSchoolPlanError
from jireh.financial_aid.assessment_contract import CandidateAssessmentError
from jireh.financial_aid.fictional_planning_need import fictional_planning_context
from jireh.financial_aid.models import AidApplication
from jireh.financial_aid.questionnaire_validation import QuestionnaireValidationError
from jireh.financial_aid.school_plan_revisions import (
    read_fictional_school_plan, record_fictional_school_plan,
)
from jireh.financial_aid.synthetic_questionnaire_preview import require_synthetic_questionnaire_preview
from .demo_seed import DEMO_SCHOOL_A_CODE
from .grant_admin import _lock_authorized_school
from .workspace_contributor_exception import contributor_review_pending


@dataclass(frozen=True, slots=True, repr=False)
class SavedNeedFixture:
    school_id: UUID
    academic_year_id: UUID
    household_id: UUID
    grades: tuple[tuple[UUID, str], ...]


def configure_saved_need_fixture(demo):
    """Seed the plan only at explicit disposable startup, not on a GET request."""
    require_synthetic_questionnaire_preview()
    if (getattr(settings, "JIREH_CUSTOMER_WORKSPACE_ACCEPTANCE", False) is not True
            or demo["school_a"].code != DEMO_SCHOOL_A_CODE):
        raise PermissionDenied("Fictional saved need unavailable.")
    record_fictional_school_plan(
        user=demo["director_a"], school_id=demo["school_a"].pk,
        academic_year_id=demo["year_a"].pk, plan=FICTIONAL_15145_PLAN,
    )
    # Only the explicitly seeded director receives separate rehearsal authority.
    demo["director_a"].user_permissions.add(Permission.objects.get(
        content_type__app_label="financial_aid", content_type__model="fictionalneeddecision",
        codename="add_fictionalneeddecision",
    ))
    return SavedNeedFixture(
        demo["school_a"].pk, demo["year_a"].pk, demo["household_a"].pk,
        ((demo["student_a1"].pk, "elementary"), (demo["student_a2"].pk, "middle")),
    )


@transaction.atomic
def read_saved_need_preview(
    *, user, school, year, application_id, questionnaire_revision,
    expected_plan_revision=None, scenario_committed_aid_cents=0,
    scenario_proposed_aid_cents=0, changed_income_review=None, assessment_date=None,
):
    """No client-supplied geography, grades, rule parameters or raw financial rows.

    The only enabled context is the exact seeded fictional family. The school
    lock serializes the contributor hold with calculation and grant readback.
    The existing calculation independently verifies current revision and scope.
    """
    fixture = getattr(settings, "JIREH_SAVED_NEED_FIXTURE", None)
    if (type(fixture) is not SavedNeedFixture
            or school.code != DEMO_SCHOOL_A_CODE
            or (fixture.school_id, fixture.academic_year_id) != (school.pk, year.pk)):
        return None
    require_synthetic_questionnaire_preview()
    _lock_authorized_school(actor=user, school_id=school.pk)
    draft = AidApplication.objects.for_school(school.pk).filter(
        pk=application_id, academic_year=year, household_id=fixture.household_id,
        household__is_active=True, status=AidApplication.STATUS_DRAFT,
    ).first()
    if draft is None:
        return None
    if contributor_review_pending(draft.pk):
        return {"status": "held"}
    if questionnaire_revision is None or getattr(settings, "JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE", False) is not True:
        return {"status": "unavailable"}
    try:
        # Optional cryptography must not prevent the basic local demo from starting.
        from jireh.financial_aid.saved_fictional_need import (
            SavedFictionalNeedContext, SavedFictionalNeedError, calculate_saved_fictional_need,
        )
        from .workspace_questionnaire import fictional_questionnaire_policy
    except ImportError:
        return {"status": "unavailable"}
    try:
        plan = read_fictional_school_plan(user=user, school_id=school.pk, academic_year_id=year.pk)
        if plan is None or (expected_plan_revision is not None
                            and plan.revision != expected_plan_revision):
            return {"status": "unavailable"}
        policy, _ = fictional_questionnaire_policy(draft)
        catalog = json.loads((Path(__file__).resolve().parents[3] / "docs" /
                              "questionnaire_v1_field_catalog.json").read_text(encoding="utf-8"))
        result = calculate_saved_fictional_need(
            user=user, catalog=catalog, key=getattr(settings, "JIREH_SYNTHETIC_QUESTIONNAIRE_KEY", None),
            context=SavedFictionalNeedContext(
                school_id=school.pk, academic_year_id=year.pk, application_id=draft.pk,
                questionnaire_revision=questionnaire_revision, plan_revision=plan.revision,
                grade_assignments=fixture.grades, questionnaire_policy=policy,
                balance_date=date(2026, 6, 30),
                scenario_committed_aid_cents=scenario_committed_aid_cents,
                scenario_proposed_aid_cents=scenario_proposed_aid_cents,
                changed_income_review=changed_income_review, assessment_date=assessment_date,
                **fictional_planning_context(),
            ),
        )
    except (SavedFictionalNeedError, QuestionnaireValidationError, CandidateAssessmentError,
            AnnualSchoolPlanError, ValidationError, OSError, UnicodeError, json.JSONDecodeError):
        return {"status": "unavailable"}
    # This is a need-only hypothetical projection, not an adopted award rule.
    # Other award buckets and exceptions require separately established evidence.
    if scenario_proposed_aid_cents > result.regional_need.unmet_tuition_cents:
        return {"status": "unavailable"}
    # Display only aggregates. No household source rows, contributor IDs,
    # decrypted documents, credentials or school-authorized decisions.
    return {
        "status": "available",
        "questionnaire_id": result.questionnaire_id,
        "questionnaire_revision": result.questionnaire_revision,
        "plan_id": result.plan_id,
        "plan_revision": result.plan_revision,
        "open_seats": plan.as_plan().open_seats,
        "calculation_version": result.regional_need.calculation_version,
        "dataset_sha256": result.regional_need.dataset_sha256,
        "net_tuition_cents": result.cost.net_tuition_cents,
        "allowance_cents": result.regional_need.allowance_cents,
        "contribution_cents": result.regional_need.expected_contribution_cents,
        "unmet_tuition_cents": result.regional_need.unmet_tuition_cents,
        "projection": {
            "committed_cents": scenario_committed_aid_cents,
            "proposed_cents": scenario_proposed_aid_cents,
            "household_balance_cents": result.projection.household_balance_cents,
            "remaining_budget_cents": result.projection.remaining_aid_budget_cents,
        },
    }
