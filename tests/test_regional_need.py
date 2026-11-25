"""Fictional comparisons for address-derived regional need."""

from dataclasses import replace
from unittest import TestCase

from jireh.financial_aid.assessment_contract import CandidateAssessmentError, calculate_candidate_assessment
from jireh.financial_aid.buckets import AidBucket
from jireh.financial_aid.regional_need import (
    FictionalLivingAllowance,
    FictionalLivingAllowanceTable,
    FictionalRegionalNeedInput,
    FictionalRegionalNeedPolicy,
    calculate_fictional_regional_need,
)
from test_assessment_contract import SCHOOL_A, YEAR_A, policy


class FictionalRegionalNeedTests(TestCase):
    def setUp(self):
        self.inputs = FictionalRegionalNeedInput(
            region_code="fictional-region-a", adults=1, children=2, address_verified=True,
            eligible_income_cents=100_000, assets_cents=20_000,
            deductible_liabilities_cents=4_000, tuition_cents=85_000,
        )
        self.table = FictionalLivingAllowanceTable("fictional-budget-v1", 2026, (
            FictionalLivingAllowance("fictional-region-a", 1, 2, 10_000),
            FictionalLivingAllowance("fictional-region-b", 1, 2, 40_000),
            FictionalLivingAllowance("fictional-region-a", 2, 1, 20_000),
        ))
        self.rules = FictionalRegionalNeedPolicy(
            dataset_version="fictional-budget-v1", dataset_year=2026,
            dataset_sha256="7e9815cf60beacc4f2bf815fa5835eaaf1a2fbfae621687a14186e9d0b267ae2",
            income_contribution_bps=5_000, asset_contribution_bps=2_500, rounding="HALF_UP",
        )

    def calculate(self, **overrides):
        params = {"inputs": self.inputs, "table": self.table, "policy": self.rules}
        return calculate_fictional_regional_need(**(params | overrides))

    def test_same_finances_in_different_regions_change_the_need_recommendation(self):
        lower_cost = self.calculate()
        higher_cost = self.calculate(inputs=replace(self.inputs, region_code="fictional-region-b"))
        self.assertEqual((lower_cost.allowance_cents, higher_cost.allowance_cents), (10_000, 40_000))
        self.assertEqual((lower_cost.available_income_cents, higher_cost.available_income_cents), (90_000, 60_000))
        self.assertEqual(lower_cost.net_assets_cents, 16_000)
        self.assertEqual((lower_cost.expected_contribution_cents, higher_cost.expected_contribution_cents),
                         (49_000, 34_000))
        self.assertEqual((lower_cost.unmet_tuition_cents, higher_cost.unmet_tuition_cents), (36_000, 51_000))
        self.assertEqual((higher_cost.dataset_version, higher_cost.dataset_year), ("fictional-budget-v1", 2026))
        self.assertEqual(higher_cost.dataset_sha256, self.rules.dataset_sha256)
        self.assertEqual(higher_cost.region_code, "fictional-region-b")
        recommendations = []
        for calculation in (lower_cost, higher_cost):
            basis = dict.fromkeys(AidBucket, 0)
            basis[AidBucket.NEED] = calculation.unmet_tuition_cents
            assessment = calculate_candidate_assessment(
                policy=policy(), school_id=SCHOOL_A, academic_year_id=YEAR_A, basis_cents_by_bucket=basis,
            )
            recommendations.append(next(line.recommendation_cents for line in assessment.lines
                                        if line.bucket is AidBucket.NEED))
            self.assertTrue(assessment.requires_school_authorization)
        self.assertEqual(recommendations, [9_000, 12_750])

    def test_same_size_households_use_their_own_adult_and_child_counts(self):
        result = self.calculate(inputs=replace(self.inputs, adults=2, children=1))
        self.assertEqual(result.allowance_cents, 20_000)

    def test_missing_or_unverified_residence_and_unsupported_household_fail_closed(self):
        for inputs, code in (
            (replace(self.inputs, region_code=None), "regional_need_location_unverified"),
            (replace(self.inputs, address_verified=False), "regional_need_location_unverified"),
            (replace(self.inputs, address_verified=1), "regional_need_location_unverified"),
            (replace(self.inputs, region_code="unknown"), "regional_need_allowance_unavailable"),
            (replace(self.inputs, adults=1, children=6), "regional_need_allowance_unavailable"),
            (replace(self.inputs, adults=True), "regional_need_household_invalid"),
        ):
            with self.subTest(code=code), self.assertRaisesRegex(CandidateAssessmentError, f"^{code}$"):
                self.calculate(inputs=inputs)

    def test_requires_exact_dataset_identity_and_unambiguous_rows(self):
        for table in (replace(self.table, dataset_year=2025), replace(self.table, dataset_version="new-v2")):
            with self.assertRaisesRegex(CandidateAssessmentError, "^regional_need_dataset_mismatch$"):
                self.calculate(table=table)
        duplicate = replace(self.table.allowances[0], annual_cents=99)
        with self.assertRaisesRegex(CandidateAssessmentError, "^regional_need_allowance_duplicate$"):
            self.calculate(table=replace(self.table, allowances=(*self.table.allowances, duplicate)))

    def test_rejects_modified_dataset_contents_even_when_version_and_year_match(self):
        unchanged = replace(self.table, allowances=tuple(reversed(self.table.allowances)))
        self.assertEqual(self.calculate(table=unchanged), self.calculate())
        first, *remaining = self.table.allowances
        modified = replace(self.table, allowances=(replace(first, annual_cents=10_001), *remaining))
        with self.assertRaisesRegex(CandidateAssessmentError, "^regional_need_dataset_digest_mismatch$"):
            self.calculate(table=modified)

    def test_clamps_at_zero_and_rounds_the_combined_contribution_once(self):
        result = self.calculate(inputs=replace(self.inputs, eligible_income_cents=10_001,
                                               assets_cents=1, deductible_liabilities_cents=0))
        self.assertEqual(result.expected_contribution_cents, 1)
        result = self.calculate(inputs=replace(self.inputs, eligible_income_cents=1,
                                               assets_cents=0, deductible_liabilities_cents=1))
        self.assertEqual(result.expected_contribution_cents, 0)
        result = self.calculate(inputs=replace(self.inputs, tuition_cents=1))
        self.assertEqual(result.unmet_tuition_cents, 0)

    def test_rejects_invalid_financial_values_and_policy_parameters(self):
        for inputs in (
            replace(self.inputs, eligible_income_cents=True),
            replace(self.inputs, deductible_liabilities_cents=-1),
            replace(self.inputs, tuition_cents=0),
        ):
            with self.assertRaises(CandidateAssessmentError):
                self.calculate(inputs=inputs)
        for rules in (
            replace(self.rules, dataset_sha256="z" * 64),
            replace(self.rules, income_contribution_bps=10_001),
            replace(self.rules, asset_contribution_bps=True),
            replace(self.rules, rounding="nearest"),
        ):
            with self.assertRaisesRegex(CandidateAssessmentError, "^regional_need_policy_invalid$"):
                self.calculate(policy=rules)
