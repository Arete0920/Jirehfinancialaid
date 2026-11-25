"""Readback of one explicitly seeded enrollment scenario in the disposable case."""

from datetime import date

from django.conf import settings

from jireh.financial_aid.annual_school_plan import family_education_cost
from jireh.financial_aid.fictional_enrollment_preview import (
    FictionalEnrollmentCandidate, FictionalEnrollmentPlanSnapshot, FictionalEnrollmentPolicy,
    preview_fictional_enrollment,
)
from jireh.financial_aid.models import AidApplication
from jireh.financial_aid.school_plan_revisions import read_fictional_school_plan
from jireh.financial_aid.synthetic_questionnaire_preview import require_synthetic_questionnaire_preview
from .fictional_need_decisions import fixture_matches


_AS_OF = date(2026, 11, 25)
_GRADE = "elementary"
_COHORT = "first-time"
_LIMIT_LABELS = {
    "student_cap": "Student cap",
    "program_budget": "Remaining enrollment pool",
    "school_budget": "Remaining school budget",
    "eligible_tuition": "Eligible tuition after other support",
}


def read_fictional_enrollment_case(*, user, school, year, application_id, selected_student_ids):
    """Use the current immutable plan and the seeded scenario, never family amounts."""
    if not fixture_matches(school.pk, year.pk):
        return None
    require_synthetic_questionnaire_preview()
    fixture = settings.JIREH_SAVED_NEED_FIXTURE
    plan_row = read_fictional_school_plan(user=user, school_id=school.pk, academic_year_id=year.pk)
    if not AidApplication.objects.for_school(school.pk).filter(
        pk=application_id, academic_year=year, household_id=fixture.household_id,
        household__is_active=True, status=AidApplication.STATUS_DRAFT,
    ).exists():
        return None
    if plan_row is None or plan_row.pk != fixture.enrollment_plan_id:
        return {"state": "plan_stale"}
    selected = set(selected_student_ids)
    grades = tuple(grade for student, grade in fixture.grades if str(student) in selected)
    if _GRADE not in grades or len(grades) != len(selected):
        return {"state": "student_unselected"}

    plan = plan_row.as_plan()
    scope = {"school_id": str(school.pk), "academic_year_id": str(year.pk)}
    policy = FictionalEnrollmentPolicy(
        **scope, version="fictional-elementary-enrollment-v1", eligible_grade_cohorts=((_GRADE, _COHORT),),
        effective_from=date(2026, 11, 1), effective_through=date(2026, 12, 15), max_vacancy_age_days=7,
        program_budget_cents=1_500_000, student_cap_cents=100_000, permits_stacking=True,
    )
    snapshot = FictionalEnrollmentPlanSnapshot(
        **scope, plan_id=str(plan_row.pk), revision=plan_row.revision, observed_on=_AS_OF, plan=plan,
    )
    costs = family_education_cost(plan, grades)
    elementary_tuition = next(band.tuition_cents for band in plan.grade_bands if band.code == _GRADE)
    # The elementary student has the lower tuition in the seeded sibling
    # pair. Family pricing supplies zero discount for a one-student selection.
    eligible_tuition = elementary_tuition - costs.discount_cents
    result = preview_fictional_enrollment(
        policy=policy, snapshot=snapshot,
        candidate=FictionalEnrollmentCandidate(
            **scope, plan_id=snapshot.plan_id, plan_revision=snapshot.revision, policy_version=policy.version,
            grade_band=_GRADE, cohort=_COHORT, as_of=_AS_OF, net_eligible_tuition_cents=eligible_tuition,
            other_applicable_aid_cents=0, program_committed_cents=0, school_committed_cents=0,
        ),
    )
    return {
        "state": result.state, "maximum_cents": result.maximum_review_cents, "open_seats": result.open_seats,
        "pool_cents": policy.program_budget_cents, "cap_cents": policy.student_cap_cents,
        "policy_version": result.policy_version, "plan_revision": result.plan_revision, "as_of": _AS_OF,
        "limits": tuple(_LIMIT_LABELS[factor] for factor in result.limiting_factors),
    }
