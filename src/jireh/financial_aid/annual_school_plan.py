"""Offline annual tuition, seat and budget planning for a fictional school."""

from dataclasses import dataclass
import re

from .assessment_contract import _rounded_nonnegative


class AnnualSchoolPlanError(ValueError):
    """Stable validation error for an invalid planning input."""


def _nonnegative_integer(value):
    return type(value) is int and value >= 0


@dataclass(frozen=True, slots=True)
class FictionalGradeBand:
    code: str
    label: str
    capacity: int
    enrolled: int
    tuition_cents: int

    def __post_init__(self):
        if (
            type(self.code) is not str or not self.code.strip()
            or type(self.label) is not str or not self.label.strip()
            or not _nonnegative_integer(self.capacity) or self.capacity == 0
            or not _nonnegative_integer(self.enrolled) or self.enrolled > self.capacity
            or not _nonnegative_integer(self.tuition_cents) or self.tuition_cents == 0
        ):
            raise AnnualSchoolPlanError("grade_band_invalid")

    @property
    def open_seats(self):
        return self.capacity - self.enrolled


@dataclass(frozen=True, slots=True)
class FictionalAnnualSchoolPlan:
    postal_code: str
    grade_bands: tuple[FictionalGradeBand, ...]
    required_fee_cents: int
    sibling_discount_bps: int
    annual_aid_budget_cents: int

    def __post_init__(self):
        if (
            type(self.postal_code) is not str or re.fullmatch(r"[0-9]{5}", self.postal_code) is None
            or type(self.grade_bands) is not tuple or not self.grade_bands
            or any(type(band) is not FictionalGradeBand for band in self.grade_bands)
            or not _nonnegative_integer(self.required_fee_cents)
            or not _nonnegative_integer(self.sibling_discount_bps) or self.sibling_discount_bps > 10_000
            or not _nonnegative_integer(self.annual_aid_budget_cents)
        ):
            raise AnnualSchoolPlanError("school_plan_invalid")
        if len({band.code for band in self.grade_bands}) != len(self.grade_bands):
            raise AnnualSchoolPlanError("grade_band_duplicate")

    @property
    def capacity(self):
        return sum(band.capacity for band in self.grade_bands)

    @property
    def enrolled(self):
        return sum(band.enrolled for band in self.grade_bands)

    @property
    def open_seats(self):
        return self.capacity - self.enrolled

    @property
    def average_tuition_cents(self):
        full_capacity_tuition = sum(band.tuition_cents * band.capacity for band in self.grade_bands)
        return _rounded_nonnegative(full_capacity_tuition, self.capacity, "HALF_UP")


FICTIONAL_15145_PLAN = FictionalAnnualSchoolPlan(
    postal_code="15145",
    grade_bands=(
        FictionalGradeBand("prek", "Pre-K 3–4", 40, 34, 950_000),
        FictionalGradeBand("elementary", "K–5", 150, 128, 1_175_000),
        FictionalGradeBand("middle", "6–8", 90, 75, 1_325_000),
        FictionalGradeBand("high", "9–12", 120, 98, 1_387_500),
    ),
    required_fee_cents=50_000,
    sibling_discount_bps=1_000,
    annual_aid_budget_cents=25_000_000,
)


@dataclass(frozen=True, slots=True, repr=False)
class FictionalFamilyEducationCost:
    sticker_tuition_cents: int
    discount_cents: int
    required_fees_cents: int

    @property
    def net_tuition_cents(self):
        return self.sticker_tuition_cents - self.discount_cents

    @property
    def eligible_cost_cents(self):
        return self.net_tuition_cents + self.required_fees_cents


def family_education_cost(
    plan: FictionalAnnualSchoolPlan, grade_band_codes: tuple[str, ...],
) -> FictionalFamilyEducationCost:
    """Price the supported one- and two-student fictional households."""
    if (type(plan) is not FictionalAnnualSchoolPlan
            or type(grade_band_codes) is not tuple or not 1 <= len(grade_band_codes) <= 2
            or any(type(code) is not str for code in grade_band_codes)):
        raise AnnualSchoolPlanError("family_plan_invalid")
    rates = {band.code: band.tuition_cents for band in plan.grade_bands}
    if any(code not in rates for code in grade_band_codes):
        raise AnnualSchoolPlanError("family_grade_band_unknown")
    tuition = [rates[code] for code in grade_band_codes]
    discount = 0
    if len(tuition) == 2:
        discount = _rounded_nonnegative(min(tuition) * plan.sibling_discount_bps, 10_000, "HALF_UP")
    return FictionalFamilyEducationCost(sum(tuition), discount, plan.required_fee_cents * len(tuition))


@dataclass(frozen=True, slots=True, repr=False)
class FictionalAwardProjection:
    net_tuition_after_aid_cents: int
    household_balance_cents: int
    remaining_aid_budget_cents: int


def project_fictional_award(
    plan: FictionalAnnualSchoolPlan,
    cost: FictionalFamilyEducationCost,
    *,
    committed_aid_cents: int,
    proposed_aid_cents: int,
) -> FictionalAwardProjection:
    """Model a proposal applying aid to tuition first, then eligible fees."""
    if (
        type(plan) is not FictionalAnnualSchoolPlan or type(cost) is not FictionalFamilyEducationCost
        or not _nonnegative_integer(committed_aid_cents) or not _nonnegative_integer(proposed_aid_cents)
        or not _nonnegative_integer(cost.sticker_tuition_cents)
        or not _nonnegative_integer(cost.discount_cents) or cost.discount_cents > cost.sticker_tuition_cents
        or not _nonnegative_integer(cost.required_fees_cents)
    ):
        raise AnnualSchoolPlanError("award_projection_invalid")
    remaining = plan.annual_aid_budget_cents - committed_aid_cents - proposed_aid_cents
    if remaining < 0:
        raise AnnualSchoolPlanError("award_exceeds_budget")
    if proposed_aid_cents > cost.eligible_cost_cents:
        raise AnnualSchoolPlanError("award_exceeds_cost")
    return FictionalAwardProjection(
        max(cost.net_tuition_cents - proposed_aid_cents, 0),
        cost.eligible_cost_cents - proposed_aid_cents,
        remaining,
    )
