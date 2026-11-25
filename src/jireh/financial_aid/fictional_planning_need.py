"""The fixed Pittsburgh residence and allowance assumptions for director planning."""

from .hud_area_lookup import (
    FictionalHudAddressGeography,
    FictionalHudAreaCrosswalk,
    FictionalHudAreaRow,
    resolve_fictional_hud_area,
)
from .hud_living_allowance import (
    FictionalHouseholdAllowanceRule,
    FictionalHudMonthlyRent,
    build_fictional_hud_living_allowance_table,
)
from .regional_need import (
    FictionalRegionalNeedCalculation,
    FictionalRegionalNeedInput,
    FictionalRegionalNeedPolicy,
    calculate_fictional_regional_need,
)


HUD_FMR_SOURCE = "https://www.huduser.gov/portal/datasets/fmr/fmr2027/FY27_FMRs.xlsx"
_HUD_FISCAL_YEAR = 2027
_DATASET_VERSION = "fictional-15145-fy2027-v1"
_ALLOWANCE_SHA256 = "10dc4f12ec5be0757c04de8237e9bb4c96d3a136ade0be55add75f2418d71fae"
_CROSSWALK_SHA256 = "9b23ab8b6f0c6c37c5e0bd12a3409c222ceaafedaee0117fa895f716c005269a"
# The published Allegheny County row supplies the area code and two-bedroom rent.
_PITTSBURGH_AREA = "METRO38300M38300"
_HUD_GEOGRAPHY_CODE = "4200399999"
PITTSBURGH_MONTHLY_HOUSING_CENTS = 138_900
_HOUSEHOLD = FictionalHouseholdAllowanceRule(adults=2, children=2, bedrooms=2, annual_nonhousing_cents=360_000)


def calculate_fictional_planning_need(net_tuition_cents: int) -> FictionalRegionalNeedCalculation:
    """Assess tuition after sibling discounts using the pinned fictional residence."""
    region = resolve_fictional_hud_area(
        geography=FictionalHudAddressGeography("42003", True, _HUD_GEOGRAPHY_CODE),
        crosswalk=FictionalHudAreaCrosswalk(_HUD_FISCAL_YEAR, (
            FictionalHudAreaRow(_HUD_GEOGRAPHY_CODE, _PITTSBURGH_AREA),
        )),
        expected_hud_fiscal_year=_HUD_FISCAL_YEAR,
        expected_crosswalk_sha256=_CROSSWALK_SHA256,
    )
    table = build_fictional_hud_living_allowance_table(
        dataset_version=_DATASET_VERSION,
        hud_fiscal_year=_HUD_FISCAL_YEAR,
        monthly_rents=(FictionalHudMonthlyRent(_PITTSBURGH_AREA, _HOUSEHOLD.bedrooms,
                                               PITTSBURGH_MONTHLY_HOUSING_CENTS),),
        household_rules=(_HOUSEHOLD,),
    )
    policy = FictionalRegionalNeedPolicy(_DATASET_VERSION, _HUD_FISCAL_YEAR, _ALLOWANCE_SHA256,
                                         income_contribution_bps=5_000, asset_contribution_bps=0,
                                         rounding="HALF_UP")
    inputs = FictionalRegionalNeedInput(
        region_code=region, adults=_HOUSEHOLD.adults, children=_HOUSEHOLD.children,
        address_verified=True, eligible_income_cents=4_000_000, assets_cents=0,
        deductible_liabilities_cents=0, tuition_cents=net_tuition_cents,
    )
    return calculate_fictional_regional_need(inputs=inputs, table=table, policy=policy)
