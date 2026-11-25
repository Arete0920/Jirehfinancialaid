from dataclasses import replace
from unittest import TestCase

from jireh.financial_aid.annual_school_plan import (
    AnnualSchoolPlanError, FICTIONAL_15145_PLAN, family_education_cost, project_fictional_award,
)


class AnnualSchoolPlanTests(TestCase):
    def test_fictional_setup_reconciles_capacity_tuition_and_budget(self):
        plan = FICTIONAL_15145_PLAN
        self.assertEqual((plan.capacity, plan.enrolled, plan.open_seats), (400, 335, 65))
        self.assertEqual(plan.average_tuition_cents, 1_250_000)
        self.assertEqual((plan.postal_code, plan.annual_aid_budget_cents), ("15145", 25_000_000))
        self.assertEqual(tuple(band.open_seats for band in plan.grade_bands), (6, 22, 15, 22))

    def test_discount_is_order_independent_and_applies_to_lower_tuition_only(self):
        cost = family_education_cost(FICTIONAL_15145_PLAN, ("middle", "elementary"))
        self.assertEqual(cost, family_education_cost(FICTIONAL_15145_PLAN, ("elementary", "middle")))
        self.assertEqual(cost.sticker_tuition_cents, 2_500_000)
        self.assertEqual(cost.discount_cents, 117_500)
        self.assertEqual(cost.net_tuition_cents, 2_382_500)
        self.assertEqual(cost.required_fees_cents, 100_000)
        self.assertEqual(cost.eligible_cost_cents, 2_482_500)
        self.assertEqual(family_education_cost(FICTIONAL_15145_PLAN, ("elementary",)).discount_cents, 0)
        self.assertEqual(family_education_cost(FICTIONAL_15145_PLAN, ("high", "high")).eligible_cost_cents, 2_736_250)

    def test_projection_keeps_tuition_fee_and_award_balances_separate(self):
        plan = FICTIONAL_15145_PLAN
        cost = family_education_cost(plan, ("elementary", "middle"))
        forecast = project_fictional_award(plan, cost, committed_aid_cents=100_000, proposed_aid_cents=250_000)
        self.assertEqual(forecast.net_tuition_after_aid_cents, 2_132_500)
        self.assertEqual(forecast.household_balance_cents, 2_232_500)
        self.assertEqual(forecast.remaining_aid_budget_cents, 24_650_000)
        full_aid = project_fictional_award(plan, cost, committed_aid_cents=0,
                                          proposed_aid_cents=cost.eligible_cost_cents)
        self.assertEqual((full_aid.net_tuition_after_aid_cents, full_aid.household_balance_cents), (0, 0))

    def test_invalid_settings_and_awards_fail_closed(self):
        plan = FICTIONAL_15145_PLAN
        first = plan.grade_bands[0]
        with self.assertRaisesRegex(AnnualSchoolPlanError, "^grade_band_invalid$"):
            replace(first, enrolled=41)
        for overrides in (
            {"grade_bands": (first, first)}, {"sibling_discount_bps": True},
            {"annual_aid_budget_cents": -1},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(AnnualSchoolPlanError):
                replace(plan, **overrides)
        for grades in ((), ("unknown",), ("middle",) * 3):
            with self.assertRaises(AnnualSchoolPlanError):
                family_education_cost(plan, grades)

        cost = family_education_cost(plan, ("middle",))
        with self.assertRaisesRegex(AnnualSchoolPlanError, "^award_exceeds_budget$"):
            project_fictional_award(plan, cost, committed_aid_cents=24_999_999, proposed_aid_cents=2)
        with self.assertRaisesRegex(AnnualSchoolPlanError, "^award_exceeds_cost$"):
            project_fictional_award(plan, cost, committed_aid_cents=0,
                                    proposed_aid_cents=cost.eligible_cost_cents + 1)
