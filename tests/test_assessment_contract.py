"""Offline synthetic-only five-bucket candidate assessment acceptance.

These values are NOT approved financial-aid rates or eligibility rules.
CROWN legacy formulas, religious signals, real money and family data unused.
"""
import unittest
from dataclasses import FrozenInstanceError
from uuid import uuid4

from jireh.financial_aid.assessment_contract import (
    BucketCalculationRule,
    CandidateAssessmentError,
    CandidateAssessmentPolicy,
    calculate_candidate_assessment,
)
from jireh.financial_aid.buckets import AidBucket


SCHOOL_A = str(uuid4())
SCHOOL_B = str(uuid4())
YEAR_A = str(uuid4())
YEAR_B = str(uuid4())
SYNTHETIC_CEILING = 10_000_000


def policy(
    *,
    school_id=SCHOOL_A,
    academic_year_id=YEAR_A,
    version="fictional-v1",
    numerator=1,
    denominator=4,
    rounding="FLOOR",
    maximum_basis_cents=1_000_000,
    maximum_recommendation_cents=100_000,
    total_review_ceiling_cents=SYNTHETIC_CEILING,
):
    return CandidateAssessmentPolicy(
        school_id=school_id,
        academic_year_id=academic_year_id,
        policy_version=version,
        bucket_rules=tuple(
            BucketCalculationRule(
                bucket=bucket,
                numerator=numerator,
                denominator=denominator,
                rounding=rounding,
                maximum_basis_cents=maximum_basis_cents,
                maximum_recommendation_cents=maximum_recommendation_cents,
            )
            for bucket in AidBucket
        ),
        total_review_ceiling_cents=total_review_ceiling_cents,
    )


def inputs(*, basis=1_000):
    return {bucket: basis for bucket in AidBucket}


def calculate(*, given_policy=None, school_id=SCHOOL_A, year_id=YEAR_A, amounts=None):
    return calculate_candidate_assessment(
        policy=given_policy if given_policy is not None else policy(),
        school_id=school_id,
        academic_year_id=year_id,
        basis_cents_by_bucket=amounts if amounts is not None else inputs(),
    )


class CandidateAssessmentTests(unittest.TestCase):
    def assert_rejected(self, code, **kwargs):
        with self.assertRaises(CandidateAssessmentError) as result:
            calculate(**kwargs)
        self.assertEqual(str(result.exception), code)

    def test_synthetic_all_five_buckets_explained_and_no_auto_award(self):
        result = calculate()
        self.assertEqual(result.policy_version, "fictional-v1")
        self.assertEqual(result.calculation_version, "synthetic-arithmetic-v1")
        self.assertEqual(str(result.school_id), SCHOOL_A)
        self.assertEqual(str(result.academic_year_id), YEAR_A)
        self.assertEqual(len(result.lines), 5)
        self.assertEqual(tuple(item.bucket for item in result.lines), tuple(AidBucket))
        self.assertEqual(
            [(item.basis_cents, item.numerator, item.denominator, item.rounding,
              item.uncapped_cents, item.recommendation_cents, item.cap_applied)
             for item in result.lines],
            [(1_000, 1, 4, "FLOOR", 250, 250, False)] * 5,
        )
        self.assertEqual(result.total_recommendation_cents, 1_250)
        self.assertIs(result.requires_school_authorization, True)
        self.assertFalse(hasattr(result, "award_id"))
        self.assertFalse(hasattr(result, "payment_status"))
        self.assertNotIn("1250", repr(result))
        with self.assertRaises(FrozenInstanceError):
            result.total_recommendation_cents = 10

    def test_rounding_is_explicit_and_exact_at_half_cent_boundaries(self):
        for rounding, basis, expected in (
            ("FLOOR", 1, 0),
            ("HALF_UP", 1, 1),
            ("CEILING", 1, 1),
            ("FLOOR", 3, 1),
            ("HALF_UP", 3, 2),
            ("CEILING", 3, 2),
        ):
            with self.subTest(rounding=rounding, basis=basis):
                p = policy(rounding=rounding, numerator=1, denominator=2)
                result = calculate(given_policy=p, amounts=inputs(basis=basis))
                self.assertEqual(result.lines[0].recommendation_cents, expected)

    def test_maximum_recommendation_cap_is_visible_and_not_a_budget_default(self):
        p = policy(numerator=1, denominator=1, maximum_recommendation_cents=125)
        result = calculate(given_policy=p)
        self.assertEqual(result.lines[0].uncapped_cents, 1_000)
        self.assertEqual(result.lines[0].recommendation_cents, 125)
        self.assertIs(result.lines[0].cap_applied, True)
        self.assertEqual(result.total_recommendation_cents, 625)

    def test_explicit_total_ceiling_fails_instead_of_silent_proration(self):
        p = policy(total_review_ceiling_cents=1249)
        self.assert_rejected("candidate_total_exceeds_review_ceiling", given_policy=p)
        p = policy(total_review_ceiling_cents=1250)
        self.assertEqual(calculate(given_policy=p).total_recommendation_cents, 1250)

    def test_school_and_aid_year_must_be_canonical_and_equal_to_policy(self):
        self.assert_rejected("candidate_policy_scope_mismatch", school_id=SCHOOL_B)
        self.assert_rejected("candidate_policy_scope_mismatch", year_id=YEAR_B)
        self.assert_rejected("candidate_scope_school_invalid", school_id=SCHOOL_A.upper())
        self.assert_rejected("candidate_scope_year_invalid", year_id=None)
        self.assert_rejected(
            "candidate_policy_school_invalid", given_policy=policy(school_id="bogus")
        )
        self.assert_rejected(
            "candidate_policy_year_invalid", given_policy=policy(academic_year_id="bogus")
        )

    def test_missing_policy_or_version_is_rejected_without_default(self):
        self.assert_rejected(
            "candidate_policy_missing",
            given_policy={"version": "untrusted", "rules": []},
        )
        for version in (None, "", "fictional v1", "x" * 65, True):
            with self.subTest(version=version):
                self.assert_rejected(
                    "candidate_policy_version_invalid",
                    given_policy=policy(version=version),
                )

    def test_all_bucket_rules_must_be_present_exactly_once(self):
        p = policy()
        for modified in (
            p.bucket_rules[:-1],
            p.bucket_rules + (p.bucket_rules[0],),
            p.bucket_rules[:-1] + (p.bucket_rules[0],),
            list(p.bucket_rules),
        ):
            with self.subTest(modified=type(modified)):
                candidate = CandidateAssessmentPolicy(
                    p.school_id, p.academic_year_id, p.policy_version,
                    modified, p.total_review_ceiling_cents,
                )
                self.assert_rejected(
                    "candidate_policy_bucket_set_invalid",
                    given_policy=candidate,
                )

    def test_float_boolean_negative_and_zero_denominator_are_invalid_policy(self):
        for numerator, denominator in (
            (True, 2), (1.0, 2), (-1, 4), (5, 4),
            (1, False), (1, 0), (1, 1_000_001), (1, 2.0),
        ):
            with self.subTest(numerator=numerator, denominator=denominator):
                self.assert_rejected(
                    "candidate_policy_ratio_invalid",
                    given_policy=policy(numerator=numerator, denominator=denominator),
                )

    def test_no_rounding_policy_is_guessed(self):
        for mode in (None, "", "BANKERS", "half_up", True):
            with self.subTest(mode=mode):
                self.assert_rejected(
                    "candidate_policy_rounding_invalid",
                    given_policy=policy(rounding=mode),
                )

    def test_policy_ceilings_are_exact_nonnegative_integer_cents(self):
        for limit, code, kw in (
            (None, "candidate_policy_basis_ceiling_invalid", "maximum_basis_cents"),
            (-1, "candidate_policy_bucket_ceiling_invalid", "maximum_recommendation_cents"),
            (True, "candidate_policy_total_ceiling_invalid", "total_review_ceiling_cents"),
            (1.5, "candidate_policy_total_ceiling_invalid", "total_review_ceiling_cents"),
        ):
            with self.subTest(limit=limit, key=kw):
                self.assert_rejected(code, given_policy=policy(**{kw: limit}))

    def test_basis_amounts_reject_strings_float_bool_negative_and_out_of_bounds(self):
        for value in (None, "1000", 1000.0, True, False, -1, [], {}):
            with self.subTest(value=value):
                modified = inputs()
                modified[AidBucket.NEED] = value
                self.assert_rejected(
                    "candidate_basis_amount_invalid", amounts=modified
                )
        self.assert_rejected(
            "candidate_basis_exceeds_ceiling",
            given_policy=policy(maximum_basis_cents=999),
        )

    def test_no_missing_extra_or_string_bucket_keys(self):
        good = inputs()
        for values in (
            {}, {AidBucket.NEED: 10}, dict(good, invalid=10),
            {bucket.value: 1_000 for bucket in AidBucket}, None, [],
        ):
            with self.subTest(type=type(values), length=len(values) if values else 0):
                self.assert_rejected(
                    "candidate_basis_bucket_set_invalid",
                    amounts=values if values is not None else [],
                )

    def test_zero_rate_is_explicit_not_unspecified(self):
        p = policy(numerator=0)
        result = calculate(given_policy=p)
        self.assertEqual(result.total_recommendation_cents, 0)
        self.assertTrue(all(line.recommendation_cents == 0 for line in result.lines))

    def test_error_codes_do_not_echo_financial_data_or_school_claims(self):
        private = "SYNTHETIC_UNTRUSTED_PRIVATE_AMOUNT"
        with self.assertRaises(CandidateAssessmentError) as captured:
            calculate(
                amounts={
                    AidBucket.NEED: private,
                    AidBucket.MISSION: 0,
                    AidBucket.MARKETING: 0,
                    AidBucket.MERIT: 0,
                    AidBucket.HARDSHIP: 0,
                }
            )
        self.assertEqual(str(captured.exception), "candidate_basis_amount_invalid")
        self.assertNotIn(private, str(captured.exception))


if __name__ == "__main__":
    unittest.main()
