"""Bound a fictional enrollment aid proposal using explicitly supplied rules.

The caller supplies the policy, authoritative scope, dated plan snapshot and
tuition amounts after any approved sibling-discount treatment. This offline
contract validates consistency. It grants no authority and reserves no seats
or funds. Only trusted synthetic callers may use it.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from .annual_school_plan import FictionalAnnualSchoolPlan
from .assessment_contract import _VERSION, _cents, _reject, _uuid


class EnrollmentPreviewState(StrEnum):
    AVAILABLE = "available"
    POLICY_UNAVAILABLE = "policy_unavailable"
    POLICY_STALE = "policy_stale"
    POLICY_OUTSIDE_WINDOW = "policy_outside_window"
    PLAN_STALE = "plan_stale"
    GRADE_FULL = "grade_full"
    INELIGIBLE = "ineligible"
    STACKING_DISALLOWED = "stacking_disallowed"


@dataclass(frozen=True, slots=True, repr=False)
class FictionalEnrollmentPolicy:
    school_id: str
    academic_year_id: str
    version: str
    eligible_grade_cohorts: tuple[tuple[str, str], ...]
    effective_from: date
    effective_through: date
    max_vacancy_age_days: int
    program_budget_cents: int
    student_cap_cents: int
    permits_stacking: bool


@dataclass(frozen=True, slots=True, repr=False)
class FictionalEnrollmentPlanSnapshot:
    school_id: str
    academic_year_id: str
    plan_id: str
    revision: int
    observed_on: date
    plan: FictionalAnnualSchoolPlan


@dataclass(frozen=True, slots=True, repr=False)
class FictionalEnrollmentCandidate:
    school_id: str
    academic_year_id: str
    plan_id: str
    plan_revision: int
    policy_version: str | None
    grade_band: str
    cohort: str
    as_of: date
    net_eligible_tuition_cents: int
    other_applicable_aid_cents: int
    program_committed_cents: int
    school_committed_cents: int


@dataclass(frozen=True, slots=True, repr=False)
class FictionalEnrollmentPreview:
    state: EnrollmentPreviewState
    plan_id: str
    plan_revision: int
    policy_version: str | None
    maximum_review_cents: int | None = None
    open_seats: int | None = None
    limiting_factors: tuple[str, ...] = ()
    requires_school_authorization: bool = True


def _identifier(value):
    return type(value) is str and _VERSION.fullmatch(value) is not None


def _school_year(value):
    return (
        _uuid(value.school_id, error_code="enrollment_school_scope_invalid"),
        _uuid(value.academic_year_id, error_code="enrollment_year_scope_invalid"),
    )


def _validate_policy(policy, plan):
    pairs = policy.eligible_grade_cohorts
    grades = {band.code for band in plan.grade_bands}
    if (
        not _identifier(policy.version)
        or type(pairs) is not tuple or not pairs
        or any(type(pair) is not tuple or len(pair) != 2
               or not all(_identifier(value) for value in pair) or pair[0] not in grades for pair in pairs)
        or len(set(pairs)) != len(pairs)
        or type(policy.effective_from) is not date or type(policy.effective_through) is not date
        or policy.effective_from > policy.effective_through
        or type(policy.permits_stacking) is not bool
    ):
        _reject("enrollment_policy_invalid")
    _cents(policy.max_vacancy_age_days, error_code="enrollment_policy_invalid")
    _cents(policy.student_cap_cents, error_code="enrollment_policy_invalid")
    if _cents(policy.program_budget_cents, error_code="enrollment_policy_invalid") > plan.annual_aid_budget_cents:
        _reject("enrollment_program_budget_exceeds_school_budget")


def preview_fictional_enrollment(
    *, snapshot: FictionalEnrollmentPlanSnapshot, policy: FictionalEnrollmentPolicy | None,
    candidate: FictionalEnrollmentCandidate,
) -> FictionalEnrollmentPreview:
    """Return an explainable ceiling or an evidence status without an amount."""
    if type(snapshot) is not FictionalEnrollmentPlanSnapshot or type(candidate) is not FictionalEnrollmentCandidate:
        _reject("enrollment_preview_input_invalid")
    if (
        _school_year(candidate) != _school_year(snapshot)
        or _uuid(candidate.plan_id, error_code="enrollment_plan_scope_invalid")
        != _uuid(snapshot.plan_id, error_code="enrollment_plan_scope_invalid")
    ):
        _reject("enrollment_scope_mismatch")
    if (
        type(snapshot.plan) is not FictionalAnnualSchoolPlan
        or type(snapshot.observed_on) is not date or type(candidate.as_of) is not date
        or any(type(value) is not int or value < 1 for value in (snapshot.revision, candidate.plan_revision))
        or (candidate.policy_version is not None and not _identifier(candidate.policy_version))
        or not _identifier(candidate.grade_band) or not _identifier(candidate.cohort)
    ):
        _reject("enrollment_preview_input_invalid")
    if policy is not None:
        if type(policy) is not FictionalEnrollmentPolicy:
            _reject("enrollment_policy_invalid")
        if _school_year(policy) != _school_year(candidate):
            _reject("enrollment_policy_scope_mismatch")
        _validate_policy(policy, snapshot.plan)
    base = {
        "plan_id": snapshot.plan_id, "plan_revision": snapshot.revision,
        "policy_version": policy.version if policy else None,
    }
    if policy is None:
        return FictionalEnrollmentPreview(EnrollmentPreviewState.POLICY_UNAVAILABLE, **base)
    if candidate.policy_version != policy.version:
        return FictionalEnrollmentPreview(EnrollmentPreviewState.POLICY_STALE, **base)
    if not policy.effective_from <= candidate.as_of <= policy.effective_through:
        return FictionalEnrollmentPreview(EnrollmentPreviewState.POLICY_OUTSIDE_WINDOW, **base)
    if (
        candidate.plan_revision != snapshot.revision
        or not 0 <= (candidate.as_of - snapshot.observed_on).days <= policy.max_vacancy_age_days
    ):
        return FictionalEnrollmentPreview(EnrollmentPreviewState.PLAN_STALE, **base)
    if (candidate.grade_band, candidate.cohort) not in policy.eligible_grade_cohorts:
        return FictionalEnrollmentPreview(EnrollmentPreviewState.INELIGIBLE, **base)
    band = next(band for band in snapshot.plan.grade_bands if band.code == candidate.grade_band)
    if not band.open_seats:
        return FictionalEnrollmentPreview(EnrollmentPreviewState.GRADE_FULL, open_seats=0, **base)

    tuition = _cents(candidate.net_eligible_tuition_cents, error_code="enrollment_tuition_invalid")
    other_aid = _cents(candidate.other_applicable_aid_cents, error_code="enrollment_other_aid_invalid")
    program_committed = _cents(candidate.program_committed_cents, error_code="enrollment_program_commitment_invalid")
    school_committed = _cents(candidate.school_committed_cents, error_code="enrollment_school_commitment_invalid")
    if other_aid > tuition or tuition > band.tuition_cents:
        _reject("enrollment_tuition_inconsistent")
    if (
        program_committed > policy.program_budget_cents or program_committed > school_committed
        or school_committed > snapshot.plan.annual_aid_budget_cents
    ):
        _reject("enrollment_budget_inconsistent")
    if other_aid and not policy.permits_stacking:
        return FictionalEnrollmentPreview(EnrollmentPreviewState.STACKING_DISALLOWED, **base)
    limits = {
        "student_cap": policy.student_cap_cents,
        "program_budget": policy.program_budget_cents - program_committed,
        "school_budget": snapshot.plan.annual_aid_budget_cents - school_committed,
        "eligible_tuition": tuition - other_aid,
    }
    maximum = min(limits.values())
    return FictionalEnrollmentPreview(
        EnrollmentPreviewState.AVAILABLE, **base, maximum_review_cents=maximum, open_seats=band.open_seats,
        limiting_factors=tuple(factor for factor, ceiling in limits.items() if ceiling == maximum),
    )
