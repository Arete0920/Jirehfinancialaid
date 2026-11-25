"""Integrate saved fictional financial rows, tuition revisions and regional need.

Only trusted, disposable callers may supply the explicit rehearsal context.
No HTTP input, residence verification service, live methodology, grant creation,
submission, award or payment is introduced. Never infer household composition,
grade bands, financial eligibility or dates from incomplete records.
"""
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404

from jireh.schools.demo_seed import DEMO_SCHOOL_A_CODE
from jireh.schools.grant_admin import _lock_authorized_school
from jireh.schools.models import AcademicYear, HouseholdAccess

from .annual_school_plan import (
    FictionalAwardProjection, FictionalFamilyEducationCost,
    family_education_cost, project_fictional_award,
)
from .hud_area_lookup import (
    FictionalHudAddressGeography, FictionalHudAreaCrosswalk, resolve_fictional_hud_area,
)
from .models import AidApplication, AidApplicationStudent, SyntheticQuestionnaireDraft
from .questionnaire_candidate import validate_v1_financial_candidate
from .regional_need import (
    FictionalLivingAllowanceTable, FictionalRegionalNeedCalculation,
    FictionalRegionalNeedInput, FictionalRegionalNeedPolicy, calculate_fictional_regional_need,
)
from .school_plan_revisions import read_fictional_school_plan
from .synthetic_questionnaire_preview import require_synthetic_questionnaire_preview
from .synthetic_questionnaire_storage import FictionalQuestionnairePolicy, _decrypt, _guard


class SavedFictionalNeedError(ValueError):
    """Stable, nonsensitive integration failure."""


@dataclass(frozen=True, slots=True, repr=False)
class SavedFictionalNeedContext:
    school_id: UUID
    academic_year_id: UUID
    application_id: UUID
    questionnaire_revision: int
    plan_revision: int
    grade_assignments: tuple[tuple[UUID, str], ...]
    adults: int
    children: int
    geography: FictionalHudAddressGeography
    crosswalk: FictionalHudAreaCrosswalk
    crosswalk_sha256: str
    allowance_table: FictionalLivingAllowanceTable
    regional_policy: FictionalRegionalNeedPolicy
    questionnaire_policy: FictionalQuestionnairePolicy
    balance_date: date
    # These are scenario inputs, not reported committed school funds.
    scenario_committed_aid_cents: int
    scenario_proposed_aid_cents: int


@dataclass(frozen=True, slots=True, repr=False)
class SavedFictionalNeedResult:
    school_id: UUID
    academic_year_id: UUID
    application_id: UUID
    questionnaire_id: UUID
    questionnaire_revision: int
    plan_id: UUID
    plan_revision: int
    cost: FictionalFamilyEducationCost
    regional_need: FictionalRegionalNeedCalculation
    projection: FictionalAwardProjection
    requires_school_authorization: bool = True
    financial_verification_established: bool = False


_SECTIONS = ("income", "assets", "liabilities", "expenses")


def _require_context(context):
    if (
        type(context) is not SavedFictionalNeedContext
        or any(type(value) is not UUID or value.int == 0 for value in (
            context.school_id, context.academic_year_id, context.application_id,
        ))
        or any(type(value) is not int or value < 1 for value in (
            context.questionnaire_revision, context.plan_revision, context.adults,
        ))
        or type(context.children) is not int or context.children < 1
        or type(context.grade_assignments) is not tuple
        or not 1 <= len(context.grade_assignments) <= 2
        or len(context.grade_assignments) > context.children
        or type(context.regional_policy) is not FictionalRegionalNeedPolicy
        or type(context.questionnaire_policy) is not FictionalQuestionnairePolicy
        or type(context.balance_date) is not date
        or context.balance_date.year != context.questionnaire_policy.reporting_year
        or type(context.questionnaire_policy.categories) is not tuple
        or len(context.questionnaire_policy.categories) != len(_SECTIONS)
    ):
        raise SavedFictionalNeedError("saved_need_context_invalid")
    assignments = {}
    for row in context.grade_assignments:
        if (
            type(row) is not tuple or len(row) != 2
            or type(row[0]) is not UUID or row[0].int == 0
            or type(row[1]) is not str or not row[1]
            or row[0] in assignments
        ):
            raise SavedFictionalNeedError("saved_need_grade_assignment_invalid")
        assignments[row[0]] = row[1]
    return assignments


def _financial_totals(answers, *, catalog, context):
    policy = context.questionnaire_policy
    if type(answers) is not dict or set(answers) - {*_SECTIONS, "school_questions"}:
        raise SavedFictionalNeedError("saved_need_answers_invalid")
    totals = {}
    for index, section in enumerate(_SECTIONS):
        rows = answers.get(section)
        if type(rows) is not list or not 1 <= len(rows) <= 32:
            raise SavedFictionalNeedError("saved_need_financial_section_incomplete")
        seen = set()
        total = 0
        for row in rows:
            validated = validate_v1_financial_candidate(
                catalog=catalog, section=section, record=row,
                approved_categories=policy.categories[index],
                min_cents=policy.min_cents, max_cents=policy.max_cents,
                reporting_year=policy.reporting_year,
                authorized_member_ids=policy.member_ids,
            )
            value = validated.value
            if section == "expenses":
                # Validate only. The regional allowance already covers living
                # costs; do not subtract itemized expenses a second time.
                continue
            identity = (validated.category, validated.member_id)
            if identity in seen:
                raise SavedFictionalNeedError("saved_need_ambiguous_financial_rows")
            seen.add(identity)
            if section == "income":
                if (value.period_start != date(policy.reporting_year, 1, 1)
                        or value.period_end != date(policy.reporting_year, 12, 31)):
                    raise SavedFictionalNeedError("saved_need_full_year_income_required")
                total += value.amount_cents
            else:
                if value.as_of_date != context.balance_date:
                    raise SavedFictionalNeedError("saved_need_balance_date_mismatch")
                total += value.balance_cents
        totals[section] = total
    return totals


@transaction.atomic
def calculate_saved_fictional_need(*, user, context, catalog, key):
    """Read actual revision-bound fictional evidence, never raw answers to caller.

    Acquire school, year and draft locks in that order to serialize grant
    changes, plan revisions and questionnaire replacement. The trusted caller
    independently supplies the fictional geography and category policy. The
    result is indicative, not proof of verified income or current legal consent.
    """
    require_synthetic_questionnaire_preview()
    _guard(key)
    assignments = _require_context(context)
    school = _lock_authorized_school(actor=user, school_id=context.school_id)
    if school.code != DEMO_SCHOOL_A_CODE:
        raise Http404("Fictional assessment unavailable.")
    year = AcademicYear.objects.for_school(school.pk).select_for_update().filter(
        pk=context.academic_year_id,
    ).first()
    if year is None:
        raise Http404("Fictional assessment unavailable.")
    draft = AidApplication.objects.for_school(school.pk).select_for_update().filter(
        pk=context.application_id, academic_year_id=year.pk,
        household__school_id=school.pk, household__is_active=True,
        status=AidApplication.STATUS_DRAFT,
    ).first()
    if draft is None:
        raise Http404("Fictional assessment unavailable.")
    plan_row = read_fictional_school_plan(
        user=user, school_id=school.pk, academic_year_id=year.pk,
    )
    if plan_row is None or plan_row.revision != context.plan_revision:
        raise SavedFictionalNeedError("saved_need_plan_revision_unavailable")
    snapshot = SyntheticQuestionnaireDraft.objects.filter(application=draft).first()
    if snapshot is None or snapshot.revision != context.questionnaire_revision:
        raise SavedFictionalNeedError("saved_need_questionnaire_revision_unavailable")
    event = snapshot.events.filter(revision=snapshot.revision).first()
    if event is None or not HouseholdAccess.objects.filter(
        household_id=draft.household_id, user_id=event.actor_user_id,
        user__is_active=True, is_active=True,
    ).exists():
        raise SavedFictionalNeedError("saved_need_source_grant_unavailable")
    selected = list(AidApplicationStudent.objects.for_school(school.pk).filter(
        application=draft,
        household_student__household_id=draft.household_id,
        household_student__student__school_id=school.pk,
    ).values_list("household_student__student_id", flat=True)[:3])
    if len(selected) != len(assignments) or set(selected) != set(assignments):
        raise SavedFictionalNeedError("saved_need_grade_scope_mismatch")

    plan = plan_row.as_plan()
    cost = family_education_cost(plan, tuple(assignments[child] for child in selected))
    totals = _financial_totals(_decrypt(snapshot, draft, key), catalog=catalog, context=context)
    region = resolve_fictional_hud_area(
        geography=context.geography, crosswalk=context.crosswalk,
        expected_hud_fiscal_year=context.regional_policy.dataset_year,
        expected_crosswalk_sha256=context.crosswalk_sha256,
    )
    need = calculate_fictional_regional_need(
        inputs=FictionalRegionalNeedInput(
            region_code=region, adults=context.adults, children=context.children,
            address_verified=True, eligible_income_cents=totals["income"],
            assets_cents=totals["assets"], deductible_liabilities_cents=totals["liabilities"],
            tuition_cents=cost.net_tuition_cents,
        ),
        table=context.allowance_table, policy=context.regional_policy,
    )
    # Scenario proposals are separate from calculated need. Do not create
    # recommendations for unresolved non-need buckets or a binding award.
    projection = project_fictional_award(
        plan, cost, committed_aid_cents=context.scenario_committed_aid_cents,
        proposed_aid_cents=context.scenario_proposed_aid_cents,
    )
    return SavedFictionalNeedResult(
        school.pk, year.pk, draft.pk, snapshot.pk, snapshot.revision,
        plan_row.pk, plan_row.revision, cost, need, projection,
    )
