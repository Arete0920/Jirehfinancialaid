"""Calculate fictional unmet tuition using a versioned regional living allowance."""

from dataclasses import dataclass
from hashlib import sha256
import json
import re

from .assessment_contract import _ROUNDING, _VERSION, _cents, _reject, _rounded_nonnegative


_BASIS_POINTS = 10_000
_CALCULATION_VERSION = "fictional-regional-need-v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True, repr=False)
class FictionalLivingAllowance:
    region_code: str
    adults: int
    children: int
    annual_cents: int


@dataclass(frozen=True, slots=True, repr=False)
class FictionalLivingAllowanceTable:
    dataset_version: str
    dataset_year: int
    allowances: tuple[FictionalLivingAllowance, ...]


@dataclass(frozen=True, slots=True, repr=False)
class FictionalRegionalNeedPolicy:
    """Supply the independently approved digest for the complete allowance table."""

    dataset_version: str
    dataset_year: int
    dataset_sha256: str
    income_contribution_bps: int
    asset_contribution_bps: int
    rounding: str


@dataclass(frozen=True, slots=True, repr=False)
class FictionalRegionalNeedInput:
    """Use trusted, fictional residence evidence and income before the living allowance.

    The caller derives the region from verified evidence. Street addresses and
    itemized household living expenses are outside this calculation.
    """

    region_code: str | None
    adults: int
    children: int
    address_verified: bool
    eligible_income_cents: int
    assets_cents: int
    deductible_liabilities_cents: int
    tuition_cents: int


@dataclass(frozen=True, slots=True, repr=False)
class FictionalRegionalNeedCalculation:
    calculation_version: str
    dataset_version: str
    dataset_year: int
    dataset_sha256: str
    region_code: str
    adults: int
    children: int
    allowance_cents: int
    available_income_cents: int
    net_assets_cents: int
    income_contribution_bps: int
    asset_contribution_bps: int
    rounding: str
    expected_contribution_cents: int
    unmet_tuition_cents: int


def _valid_identifier(value):
    return type(value) is str and _VERSION.fullmatch(value) is not None


def _valid_household(adults, children):
    return type(adults) is int and adults >= 1 and type(children) is int and children >= 0


def _living_allowance(table, policy, inputs):
    if (
        type(table) is not FictionalLivingAllowanceTable
        or not _valid_identifier(table.dataset_version)
        or type(table.dataset_year) is not int
        or not 1 <= table.dataset_year <= 9999
        or type(table.allowances) is not tuple
    ):
        _reject("regional_need_dataset_invalid")
    if (table.dataset_version, table.dataset_year) != (policy.dataset_version, policy.dataset_year):
        _reject("regional_need_dataset_mismatch")

    allowances = {}
    for row in table.allowances:
        if (
            type(row) is not FictionalLivingAllowance
            or not _valid_identifier(row.region_code)
            or not _valid_household(row.adults, row.children)
        ):
            _reject("regional_need_allowance_invalid")
        key = (row.region_code, row.adults, row.children)
        if key in allowances:
            _reject("regional_need_allowance_duplicate")
        allowances[key] = _cents(row.annual_cents, error_code="regional_need_allowance_invalid")

    # Canonical bytes cover the version, year and sorted region/adult/child/cent rows.
    rows = [[*key, amount] for key, amount in sorted(allowances.items())]
    try:
        payload = json.dumps([table.dataset_version, table.dataset_year, rows], separators=(",", ":"))
    except ValueError:
        _reject("regional_need_dataset_invalid")
    if sha256(payload.encode("ascii")).hexdigest() != policy.dataset_sha256:
        _reject("regional_need_dataset_digest_mismatch")

    key = (inputs.region_code, inputs.adults, inputs.children)
    if key not in allowances:
        _reject("regional_need_allowance_unavailable")
    return allowances[key]


def calculate_fictional_regional_need(
    *,
    inputs: FictionalRegionalNeedInput,
    table: FictionalLivingAllowanceTable,
    policy: FictionalRegionalNeedPolicy,
) -> FictionalRegionalNeedCalculation:
    """Derive an unmet-tuition basis for the existing need bucket.

    Contribution uses the supplied rates on income after the allowance and
    positive net assets. The caller supplies all rates and rounding rules.
    This function grants no authority to access data or issue an award.
    """
    if (
        type(policy) is not FictionalRegionalNeedPolicy
        or not _valid_identifier(policy.dataset_version)
        or type(policy.dataset_year) is not int
        or not 1 <= policy.dataset_year <= 9999
        or type(policy.dataset_sha256) is not str
        or _SHA256.fullmatch(policy.dataset_sha256) is None
        or type(policy.rounding) is not str
        or policy.rounding not in _ROUNDING
        or any(type(rate) is not int or not 0 <= rate <= _BASIS_POINTS
               for rate in (policy.income_contribution_bps, policy.asset_contribution_bps))
    ):
        _reject("regional_need_policy_invalid")
    if type(inputs) is not FictionalRegionalNeedInput:
        _reject("regional_need_input_invalid")
    if inputs.address_verified is not True or not _valid_identifier(inputs.region_code):
        _reject("regional_need_location_unverified")
    if not _valid_household(inputs.adults, inputs.children):
        _reject("regional_need_household_invalid")

    tuition = _cents(inputs.tuition_cents, error_code="regional_need_tuition_invalid")
    if tuition == 0:
        _reject("regional_need_tuition_invalid")
    income = _cents(inputs.eligible_income_cents, error_code="regional_need_income_invalid")
    assets = _cents(inputs.assets_cents, error_code="regional_need_assets_invalid")
    liabilities = _cents(inputs.deductible_liabilities_cents, error_code="regional_need_liabilities_invalid")
    allowance = _living_allowance(table, policy, inputs)
    available_income = max(income - allowance, 0)
    net_assets = max(assets - liabilities, 0)
    weighted_contribution = (
        available_income * policy.income_contribution_bps + net_assets * policy.asset_contribution_bps
    )
    expected_contribution = _rounded_nonnegative(weighted_contribution, _BASIS_POINTS, policy.rounding)
    return FictionalRegionalNeedCalculation(
        calculation_version=_CALCULATION_VERSION,
        dataset_version=table.dataset_version,
        dataset_year=table.dataset_year,
        dataset_sha256=policy.dataset_sha256,
        region_code=inputs.region_code,
        adults=inputs.adults,
        children=inputs.children,
        allowance_cents=allowance,
        available_income_cents=available_income,
        net_assets_cents=net_assets,
        income_contribution_bps=policy.income_contribution_bps,
        asset_contribution_bps=policy.asset_contribution_bps,
        rounding=policy.rounding,
        expected_contribution_cents=expected_contribution,
        unmet_tuition_cents=max(tuition - expected_contribution, 0),
    )
