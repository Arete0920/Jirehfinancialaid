"""Policy-driven enrollment ceiling with synthetic, nonbinding inputs."""

from dataclasses import replace
from datetime import date
from unittest import TestCase
from uuid import UUID

from jireh.financial_aid.annual_school_plan import FICTIONAL_15145_PLAN
from jireh.financial_aid.assessment_contract import CandidateAssessmentError
from jireh.financial_aid.fictional_enrollment_preview import (
    EnrollmentPreviewState, FictionalEnrollmentCandidate, FictionalEnrollmentPlanSnapshot,
    FictionalEnrollmentPolicy, preview_fictional_enrollment,
)


_SCHOOL, _YEAR, _PLAN, _OTHER = (str(UUID(int=value)) for value in range(1, 5))


class EnrollmentPreviewTests(TestCase):
    def setUp(self):
        self.plan = FictionalEnrollmentPlanSnapshot(
            school_id=_SCHOOL, academic_year_id=_YEAR, plan_id=_PLAN, revision=2,
            observed_on=date(2026, 11, 20), plan=FICTIONAL_15145_PLAN,
        )
        self.policy = FictionalEnrollmentPolicy(
            school_id=_SCHOOL, academic_year_id=_YEAR, version="fictional-enrollment-v1",
            eligible_grade_cohorts=(("elementary", "new"),), effective_from=date(2026, 11, 1),
            effective_through=date(2026, 12, 15), max_vacancy_age_days=5,
            program_budget_cents=200_000, student_cap_cents=100_000, permits_stacking=True,
        )
        self.candidate = FictionalEnrollmentCandidate(
            school_id=_SCHOOL, academic_year_id=_YEAR, plan_id=_PLAN, plan_revision=2,
            policy_version="fictional-enrollment-v1", grade_band="elementary", cohort="new", as_of=date(2026, 11, 25),
            net_eligible_tuition_cents=1_100_000, other_applicable_aid_cents=1_050_000,
            program_committed_cents=130_000, school_committed_cents=24_910_000,
        )

    def preview(self, **overrides):
        return preview_fictional_enrollment(
            **{"snapshot": self.plan, "policy": self.policy, "candidate": self.candidate, **overrides},
        )

    def test_explains_the_tightest_limit_without_reserving_a_seat_or_funds(self):
        result = self.preview()
        self.assertEqual(result, self.preview())
        self.assertEqual(result.state, EnrollmentPreviewState.AVAILABLE)
        self.assertEqual(result.maximum_review_cents, 50_000)
        self.assertEqual(result.limiting_factors, ("eligible_tuition",))
        self.assertEqual(result.open_seats, 22)
        self.assertEqual(result.policy_version, self.policy.version)
        self.assertEqual(result.plan_revision, 2)
        self.assertTrue(result.requires_school_authorization)
        self.assertEqual(self.plan.plan.open_seats, 65)

    def test_distinguishes_valid_zero_from_unavailable(self):
        zero = self.preview(candidate=replace(self.candidate, program_committed_cents=200_000))
        self.assertEqual(zero.state, EnrollmentPreviewState.AVAILABLE)
        self.assertEqual(zero.maximum_review_cents, 0)
        self.assertEqual(zero.limiting_factors, ("program_budget",))
        missing = self.preview(policy=None)
        self.assertEqual(missing.state, EnrollmentPreviewState.POLICY_UNAVAILABLE)
        self.assertIsNone(missing.maximum_review_cents)
        stale_policy = self.preview(policy=replace(self.policy, version="fictional-enrollment-v2"))
        self.assertEqual(stale_policy.state, EnrollmentPreviewState.POLICY_STALE)
        self.assertIsNone(stale_policy.maximum_review_cents)

    def test_checks_scope_revision_and_freshness(self):
        for overrides in (
            {"policy": replace(self.policy, school_id=_OTHER)},
            {"snapshot": replace(self.plan, academic_year_id=_OTHER)},
            {"candidate": replace(self.candidate, plan_id=_OTHER)},
        ):
            with self.subTest(overrides=tuple(overrides)), self.assertRaisesRegex(CandidateAssessmentError, "scope"):
                self.preview(**overrides)
        cases = (
            (replace(self.candidate, plan_revision=1), self.plan),
            (replace(self.candidate, as_of=date(2026, 11, 26)), self.plan),
            (self.candidate, replace(self.plan, observed_on=date(2026, 11, 26))),
        )
        for candidate, snapshot in cases:
            result = self.preview(candidate=candidate, snapshot=snapshot)
            self.assertEqual(result.state, EnrollmentPreviewState.PLAN_STALE)
            self.assertIsNone(result.maximum_review_cents)

    def test_enforces_cohort_grade_capacity_window_and_stacking_independently(self):
        bands = tuple(replace(band, enrolled=band.capacity) if band.code == "elementary" else band
                      for band in self.plan.plan.grade_bands)
        full = replace(self.plan, plan=replace(self.plan.plan, grade_bands=bands))
        self.assertGreater(full.plan.open_seats, 0)
        cases = (
            ({"candidate": replace(self.candidate, cohort="returning")}, EnrollmentPreviewState.INELIGIBLE),
            ({"snapshot": full}, EnrollmentPreviewState.GRADE_FULL),
            ({"policy": replace(self.policy, effective_through=date(2026, 11, 24))},
             EnrollmentPreviewState.POLICY_OUTSIDE_WINDOW),
            ({"policy": replace(self.policy, permits_stacking=False)}, EnrollmentPreviewState.STACKING_DISALLOWED),
        )
        for overrides, state in cases:
            with self.subTest(state=state):
                result = self.preview(**overrides)
                self.assertEqual(result.state, state)
                self.assertIsNone(result.maximum_review_cents)

        without_other_aid = self.preview(
            policy=replace(self.policy, permits_stacking=False),
            candidate=replace(self.candidate, other_applicable_aid_cents=0),
        )
        self.assertEqual(without_other_aid.maximum_review_cents, 70_000)
        self.assertEqual(without_other_aid.limiting_factors, ("program_budget",))

    def test_rejects_inconsistent_budgets_and_tuition_without_financial_values_in_errors(self):
        for candidate in (
            replace(self.candidate, net_eligible_tuition_cents=1_175_001),
            replace(self.candidate, program_committed_cents=200_001),
            replace(self.candidate, school_committed_cents=129_999),
            replace(self.candidate, other_applicable_aid_cents=True),
        ):
            with self.assertRaisesRegex(CandidateAssessmentError, "^enrollment_[a-z_]+$"):
                self.preview(candidate=candidate)
        result = self.preview(
            candidate=replace(self.candidate, other_applicable_aid_cents=1_000_000,
                              program_committed_cents=100_000, school_committed_cents=24_900_000),
        )
        self.assertEqual(result.maximum_review_cents, 100_000)
        self.assertEqual(result.limiting_factors, ("student_cap", "program_budget", "school_budget", "eligible_tuition"))
