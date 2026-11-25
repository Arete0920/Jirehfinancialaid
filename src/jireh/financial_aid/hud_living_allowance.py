"""Compose a fictional allowance table from normalized HUD-style gross rents."""

from dataclasses import dataclass

from .assessment_contract import _cents, _reject
from .regional_need import (
    FictionalLivingAllowance, FictionalLivingAllowanceTable, _valid_household, _valid_identifier,
)


@dataclass(frozen=True, slots=True, repr=False)
class FictionalHudMonthlyRent:
    area_code: str
    bedrooms: int
    gross_monthly_cents: int


@dataclass(frozen=True, slots=True, repr=False)
class FictionalHouseholdAllowanceRule:
    adults: int
    children: int
    bedrooms: int
    annual_nonhousing_cents: int


def _valid_bedrooms(value):
    return type(value) is int and 0 <= value <= 4


def _rents_by_area(monthly_rents):
    by_area = {}
    for row in monthly_rents:
        if (type(row) is not FictionalHudMonthlyRent
                or not _valid_identifier(row.area_code) or not _valid_bedrooms(row.bedrooms)):
            _reject("hud_allowance_rent_invalid")
        rent = _cents(row.gross_monthly_cents, error_code="hud_allowance_rent_invalid")
        if rent == 0:
            _reject("hud_allowance_rent_invalid")
        rents = by_area.setdefault(row.area_code, {})
        if row.bedrooms in rents:
            _reject("hud_allowance_rent_duplicate")
        rents[row.bedrooms] = rent
    return by_area


def _rules_by_household(household_rules):
    rules = {}
    for row in household_rules:
        if (type(row) is not FictionalHouseholdAllowanceRule
                or not _valid_household(row.adults, row.children) or not _valid_bedrooms(row.bedrooms)):
            _reject("hud_allowance_household_invalid")
        key = (row.adults, row.children)
        if key in rules:
            _reject("hud_allowance_household_duplicate")
        _cents(row.annual_nonhousing_cents, error_code="hud_allowance_nonhousing_invalid")
        rules[key] = row
    return rules


def build_fictional_hud_living_allowance_table(
    *,
    dataset_version: str,
    hud_fiscal_year: int,
    monthly_rents: tuple[FictionalHudMonthlyRent, ...],
    household_rules: tuple[FictionalHouseholdAllowanceRule, ...],
) -> FictionalLivingAllowanceTable:
    """Build annual gross rent plus an explicitly supplied nonhousing allowance.

    The caller supplies normalized rents from one fiscal-year release and
    an explicit bedroom rule for each supported household composition.
    The nonhousing allowance must exclude costs covered by gross rent,
    including covered utilities. The caller derives the HUD area outside
    this function and approves the resulting table digest independently.
    """
    if (
        not _valid_identifier(dataset_version)
        or type(hud_fiscal_year) is not int
        or not 1 <= hud_fiscal_year <= 9999
        or type(monthly_rents) is not tuple
        or not monthly_rents
        or type(household_rules) is not tuple
        or not household_rules
    ):
        _reject("hud_allowance_inputs_invalid")

    by_area = _rents_by_area(monthly_rents)
    rules = _rules_by_household(household_rules)
    ordered_rules = [rules[key] for key in sorted(rules)]
    allowances = []
    for area, rents in sorted(by_area.items()):
        for rule in ordered_rules:
            if rule.bedrooms not in rents:
                _reject("hud_allowance_rent_unavailable")
            annual_cents = 12 * rents[rule.bedrooms] + rule.annual_nonhousing_cents
            allowances.append(FictionalLivingAllowance(area, rule.adults, rule.children, annual_cents))

    return FictionalLivingAllowanceTable(dataset_version, hud_fiscal_year, tuple(allowances))
