"""Authorized, fixed-fictional financial preview for disposable Jireh tests only.

Adapt CROWN's two hardcoded family-demo scenarios from
Arete0920/Crown-CSMS@46b56609fe18360299b08eabaa8bccdffb356a0e
backend/aid/family_demo_intake.py. Validate their shapes using the standalone
31-field candidate guard. No HTTP route, questionnaire storage, consent,
submission, payment, or school-facing financial result is created by the
family preview.
"""

from types import MappingProxyType

from django.conf import settings
from django.core.exceptions import PermissionDenied

from .questionnaire_candidate import validate_v1_financial_candidate
from .questionnaire_validation import QuestionnaireValidationError
from .services import selected_student_ids_for_draft


# These two tuples are invented CROWN demo values (income, assets, debt),
# in integer USD cents. They are not financial policy or real family data.
_SCENARIOS = MappingProxyType({
    "fictional_modest": (4_800_000, 200_000, 800_000),
    "fictional_moderate": (8_200_000, 1_500_000, 300_000),
})
_SYNTHETIC_MEMBER = "11111111-1111-4111-8111-111111111111"
_SYNTHETIC_YEAR = 2026  # Invented example, NOT derived from an aid academic year.
_SYNTHETIC_MIN_CENTS = 0
_SYNTHETIC_MAX_CENTS = 100_000_000  # Test fixture limit, NOT an approved policy.
_ALLOWED_TEST_URLCONFS = frozenset((
    "jireh.schools.urls", "jireh.schools.demo_urls",
))


class FictionalScenarioNotFound(QuestionnaireValidationError):
    """The requested ID is outside the fixed scenario fixtures."""


def require_synthetic_questionnaire_preview():
    if (
        getattr(settings, "JIREH_SYNTHETIC_SUBMISSION_ONLY", False) is not True
        or settings.ROOT_URLCONF not in _ALLOWED_TEST_URLCONFS
    ):
        raise PermissionDenied("Synthetic preview unavailable.")

def validate_fictional_scenario(*, scenario_id, catalog):
    """Return validated rows from the fixed fixtures for trusted demo code."""
    if type(scenario_id) is not str or scenario_id not in _SCENARIOS:
        raise FictionalScenarioNotFound("synthetic_scenario_unavailable")
    income, assets, liabilities = _SCENARIOS[scenario_id]

    rows = (
        ("income", {
            "category": "EMPLOYMENT", "amount": income,
            "period_start": "2026-01-01", "period_end": "2026-12-31",
            "contributor_id": _SYNTHETIC_MEMBER,
        }, ("EMPLOYMENT",)),
        ("assets", {
            "category": "CASH", "balance": assets,
            "as_of_date": "2026-06-30", "owner_member_id": _SYNTHETIC_MEMBER,
        }, ("CASH",)),
        ("liabilities", {
            "category": "MORTGAGE", "balance": liabilities,
            "as_of_date": "2026-06-30", "responsible_member_id": _SYNTHETIC_MEMBER,
        }, ("MORTGAGE",)),
    )
    return {
        section: validate_v1_financial_candidate(
            catalog=catalog, section=section, record=record,
            approved_categories=categories,
            min_cents=_SYNTHETIC_MIN_CENTS,
            max_cents=_SYNTHETIC_MAX_CENTS,
            reporting_year=_SYNTHETIC_YEAR if section == "income" else None,
            authorized_member_ids=(_SYNTHETIC_MEMBER,),
        ).value
        for section, record, categories in rows
    }


def preview_fictional_financial_structure(
    *, user, school_id, household_id, academic_year_id, scenario_id, catalog
):
    """Return a value-free summary after current grant/draft authorization."""
    require_synthetic_questionnaire_preview()
    selected_student_ids_for_draft(
        user=user, school_id=school_id, household_id=household_id,
        academic_year_id=academic_year_id,
    )
    validated = validate_fictional_scenario(scenario_id=scenario_id, catalog=catalog)

    # Deliberately never expose amounts, member ID, household/student names,
    # document metadata or 'verified/submitted/awarded' status to a caller.
    return {
        "scenario_id": scenario_id,
        "demo_only": True,
        "validated_candidate_sections": list(validated),
        "full_questionnaire_complete": False,
        "financial_answers_stored": False,
        "consent_captured": False,
        "assessment_or_award_performed": False,
    }
