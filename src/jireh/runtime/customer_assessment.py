"""Read-only, fixture-scoped director assessment evidence for the existing case API.

The authenticated profile never creates a submission receipt, offer, or decision.
Only the existing pinned fictional planning methodology is eligible for a need
estimate; missing or incomplete evidence is not a zero-dollar recommendation.
"""
import json
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404

from jireh.financial_aid.assessment_contract import CandidateAssessmentError
from jireh.financial_aid.annual_school_plan import AnnualSchoolPlanError
from jireh.financial_aid.fictional_assessment_metadata import read_fictional_assessment_metadata
from jireh.financial_aid.fictional_planning_need import fictional_planning_context
from jireh.financial_aid.models import AidApplication
from jireh.financial_aid.questionnaire_validation import QuestionnaireValidationError
from jireh.financial_aid.saved_fictional_need import (
    SavedFictionalNeedContext, SavedFictionalNeedError, calculate_saved_fictional_need,
)
from jireh.financial_aid.school_plan_revisions import read_fictional_school_plan
from jireh.financial_aid.synthetic_prepayment_handoff import current_prepayment_handoff
from jireh.schools.demo_seed import DEMO_SCHOOL_A_CODE
from jireh.schools.grant_admin import _lock_authorized_school
from jireh.schools.workspace_contributor_exception import contributor_review_pending
from .customer_director_sessions import director_session_authorized
from .customer_financial_policy import financial_profile_available, financial_scope_allowed


def _need(user, draft, scope, metadata):
    # Import lazily: the existing workspace imports its assessment helpers.
    from jireh.schools.saved_need_workspace import SavedNeedFixture
    from jireh.schools.workspace_questionnaire import fictional_questionnaire_policy

    fixture = getattr(settings, "JIREH_SAVED_NEED_FIXTURE", None)
    if (type(fixture) is not SavedNeedFixture
            or (fixture.school_id, fixture.household_id, fixture.academic_year_id) != scope
            or draft.school.code != DEMO_SCHOOL_A_CODE
            or metadata.questionnaire_revision is None):
        return {"status": "unavailable"}
    if contributor_review_pending(draft.pk):
        return {"status": "held"}
    try:
        plan = read_fictional_school_plan(
            user=user, school_id=draft.school_id, academic_year_id=draft.academic_year_id,
            fixture_scope=scope,
        )
        if plan is None:
            return {"status": "unavailable"}
        policy, _ = fictional_questionnaire_policy(draft)
        catalog = json.loads((Path(__file__).resolve().parents[3] / "docs" /
                              "questionnaire_v1_field_catalog.json").read_text(encoding="utf-8"))
        result = calculate_saved_fictional_need(
            user=user, catalog=catalog, key=settings.JIREH_SYNTHETIC_QUESTIONNAIRE_KEY,
            context=SavedFictionalNeedContext(
                school_id=draft.school_id, academic_year_id=draft.academic_year_id,
                application_id=draft.pk, questionnaire_revision=metadata.questionnaire_revision,
                plan_revision=plan.revision, grade_assignments=fixture.grades,
                questionnaire_policy=policy, balance_date=date(2026, 6, 30),
                scenario_committed_aid_cents=0, scenario_proposed_aid_cents=0,
                **fictional_planning_context(),
            ), fixture_scope=scope,
        )
    except (SavedFictionalNeedError, QuestionnaireValidationError, CandidateAssessmentError,
            AnnualSchoolPlanError, ValidationError, OSError, UnicodeError, json.JSONDecodeError):
        return {"status": "unavailable"}
    return {
        "status": "available", "questionnaire_revision": result.questionnaire_revision,
        "plan_revision": result.plan_revision,
        "calculation_version": result.regional_need.calculation_version,
        "dataset_sha256": result.regional_need.dataset_sha256,
        "net_tuition_cents": result.cost.net_tuition_cents,
        "allowance_cents": result.regional_need.allowance_cents,
        "contribution_cents": result.regional_need.expected_contribution_cents,
        "unmet_tuition_cents": result.regional_need.unmet_tuition_cents,
        "requires_school_authorization": True, "financial_verification_established": False,
    }


@transaction.atomic
def read_authenticated_case_assessment(request, school_id, academic_year_id, application_id):
    """No additional route or alternate workflow; extend the existing case readback."""
    if not financial_profile_available():
        return None
    if not director_session_authorized(request, school_id):
        raise PermissionDenied()
    school = _lock_authorized_school(actor=request.user, school_id=school_id)
    draft = AidApplication.objects.for_school(school.pk).filter(
        pk=application_id, academic_year_id=academic_year_id, household__is_active=True,
        status=AidApplication.STATUS_DRAFT,
    ).first()
    if draft is None:
        raise Http404()
    scope = (school.pk, draft.household_id, academic_year_id)
    if not financial_scope_allowed(*scope):
        return None
    metadata = read_fictional_assessment_metadata(
        user=request.user, school_id=school.pk, academic_year_id=academic_year_id,
        application_id=draft.pk, fixture_scope=scope,
    )
    result = {
        "fictional_only": True,
        "questionnaire_revision": metadata.questionnaire_revision,
        "has_selected_student": metadata.has_selected_student,
        "has_active_document_metadata": metadata.has_active_document_metadata,
        "has_pending_document_removal": metadata.has_pending_document_removal,
        "has_historical_confirmation": metadata.has_historical_confirmation,
        "has_confirmation_at_saved_revision": metadata.has_confirmation_at_saved_revision,
        "contributor_review_pending": contributor_review_pending(draft.pk),
        "need": _need(request.user, draft, scope, metadata),
        "prepayment_handoff_current": current_prepayment_handoff(draft, metadata.questionnaire_revision),
        "combined_recommendation": "unavailable",
        "award_decision_available": False,
    }
    if not director_session_authorized(request, school_id):
        raise PermissionDenied()
    return result
