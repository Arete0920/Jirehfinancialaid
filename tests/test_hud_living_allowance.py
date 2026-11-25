"""Acceptance for composing fictional HUD-style rents and nonhousing costs."""

from dataclasses import replace
from unittest import TestCase

from jireh.financial_aid.assessment_contract import CandidateAssessmentError
from jireh.financial_aid.hud_area_lookup import (
    FictionalHudAddressGeography,
    FictionalHudAreaCrosswalk,
    FictionalHudAreaRow,
    resolve_fictional_hud_area,
)
from jireh.financial_aid.hud_living_allowance import (
    FictionalHouseholdAllowanceRule,
    FictionalHudMonthlyRent,
    build_fictional_hud_living_allowance_table,
)
from jireh.financial_aid.regional_need import (
    FictionalLivingAllowance,
    FictionalRegionalNeedInput,
    FictionalRegionalNeedPolicy,
    calculate_fictional_regional_need,
)


class FictionalHudLivingAllowanceTests(TestCase):
    def setUp(self):
        self.rents = (
            FictionalHudMonthlyRent("fictional-area-a", 0, 25_000),
            FictionalHudMonthlyRent("fictional-area-a", 2, 50_000),
            FictionalHudMonthlyRent("fictional-area-b", 0, 30_000),
            FictionalHudMonthlyRent("fictional-area-b", 2, 75_000),
        )
        self.rules = (
            FictionalHouseholdAllowanceRule(1, 0, 0, 120_000),
            FictionalHouseholdAllowanceRule(2, 1, 2, 360_000),
        )

    def build(self, **overrides):
        params = {
            "dataset_version": "fictional-hud-and-essentials-v1",
            "hud_fiscal_year": 2027,
            "monthly_rents": self.rents,
            "household_rules": self.rules,
        }
        return build_fictional_hud_living_allowance_table(**(params | overrides))

    def test_annualizes_gross_rent_and_adds_only_the_explicit_nonhousing_allowance(self):
        table = self.build()
        self.assertEqual(table.dataset_version, "fictional-hud-and-essentials-v1")
        self.assertEqual(table.dataset_year, 2027)
        self.assertEqual(table.allowances, (
            FictionalLivingAllowance("fictional-area-a", 1, 0, 420_000),
            FictionalLivingAllowance("fictional-area-a", 2, 1, 960_000),
            FictionalLivingAllowance("fictional-area-b", 1, 0, 480_000),
            FictionalLivingAllowance("fictional-area-b", 2, 1, 1_260_000),
        ))
        self.assertEqual(table, self.build(monthly_rents=tuple(reversed(self.rents)),
                                           household_rules=tuple(reversed(self.rules))))

    def test_composed_table_drives_the_existing_checksum_bound_need_calculator(self):
        table = self.build()
        crosswalk = FictionalHudAreaCrosswalk(2027, (
            FictionalHudAreaRow("0900301234", "fictional-area-a"),
            FictionalHudAreaRow("0900305678", "fictional-area-b"),
        ))
        inputs = FictionalRegionalNeedInput(
            region_code="fictional-area-a", adults=2, children=1, address_verified=True,
            eligible_income_cents=2_000_000, assets_cents=0,
            deductible_liabilities_cents=0, tuition_cents=600_000,
        )
        policy = FictionalRegionalNeedPolicy(
            dataset_version=table.dataset_version, dataset_year=table.dataset_year,
            dataset_sha256="d3b63dddc6ed3475b8c5aa31d90f5207feaba2247ebf47fe228a862bb2b3107b",
            income_contribution_bps=5_000, asset_contribution_bps=0, rounding="HALF_UP",
        )
        results = []
        for town_key in ("0900301234", "0900305678"):
            area = resolve_fictional_hud_area(
                geography=FictionalHudAddressGeography("09003", True, town_key),
                crosswalk=crosswalk, expected_hud_fiscal_year=table.dataset_year,
                expected_crosswalk_sha256="ead2059c6a830a42f08a95cb074c8db6b4f5de4dc9fab0549bc7b66022c371c1",
            )
            results.append(calculate_fictional_regional_need(
                inputs=replace(inputs, region_code=area), table=table, policy=policy,
            ))
        self.assertEqual([result.unmet_tuition_cents for result in results], [80_000, 230_000])
        changed = replace(self.rents[1], gross_monthly_cents=50_001)
        modified = self.build(monthly_rents=(self.rents[0], changed, *self.rents[2:]))
        with self.assertRaisesRegex(CandidateAssessmentError, "^regional_need_dataset_digest_mismatch$"):
            calculate_fictional_regional_need(inputs=inputs, table=modified, policy=policy)

    def test_rejects_missing_or_ambiguous_housing_and_household_rules(self):
        for overrides, code in (
            ({"monthly_rents": self.rents[:-1]}, "hud_allowance_rent_unavailable"),
            ({"monthly_rents": (*self.rents, self.rents[0])}, "hud_allowance_rent_duplicate"),
            ({"household_rules": (*self.rules, self.rules[0])}, "hud_allowance_household_duplicate"),
        ):
            with self.subTest(code=code), self.assertRaisesRegex(CandidateAssessmentError, f"^{code}$"):
                self.build(**overrides)

    def test_rejects_unusable_explicit_policy_and_rent_values(self):
        for overrides in (
            {"dataset_version": " "},
            {"hud_fiscal_year": True},
            {"monthly_rents": ()},
            {"household_rules": ()},
            {"monthly_rents": (replace(self.rents[0], bedrooms=5), *self.rents[1:])},
            {"monthly_rents": (replace(self.rents[0], gross_monthly_cents=0), *self.rents[1:])},
            {"household_rules": (replace(self.rules[0], annual_nonhousing_cents=True), self.rules[1])},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(CandidateAssessmentError):
                self.build(**overrides)
