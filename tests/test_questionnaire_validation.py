"""Negative tests for policy-parameterized questionnaire primitives.

Test limits (0..100000) are SYNTHETIC. They do not approve Jireh money policy,
income definitions, retention, collection, or access to financial answers.
"""
import unittest
from dataclasses import FrozenInstanceError
from datetime import date

from jireh.financial_aid.questionnaire_validation import (
    QuestionnaireValidationError,
    validate_amount_cents,
    validate_balance,
    validate_calendar_year_flow,
    validate_flow,
    validate_optional_consent,
    validate_typed_question_answer,
)


class QuestionnaireValidationTests(unittest.TestCase):
    def test_exact_integer_cents_with_explicit_bounds(self):
        self.assertEqual(validate_amount_cents(12345, min_cents=0, max_cents=100000), 12345)
        self.assertEqual(validate_amount_cents(0, min_cents=0, max_cents=100000), 0)
        self.assertEqual(validate_amount_cents(100000, min_cents=0, max_cents=100000), 100000)

    def test_missing_or_invalid_policy_bounds_are_rejected(self):
        for low, high, error in (
            (None, 100000, "money_bounds_not_configured"),
            (0, None, "money_bounds_not_configured"),
            (True, 100000, "money_bounds_not_configured"),
            (0.0, 100000, "money_bounds_not_configured"),
            (100001, 100000, "money_bounds_invalid"),
        ):
            with self.subTest(low=low, high=high):
                with self.assertRaisesRegex(QuestionnaireValidationError, "^" + error + "$"):
                    validate_amount_cents(250, min_cents=low, max_cents=high)

    def test_unanswered_is_never_coerced_to_zero(self):
        for value in (None, "", "0", "123.45", 0.0, 1.25, True, False, [], {}, [25]):
            with self.subTest(value=value):
                with self.assertRaisesRegex(QuestionnaireValidationError, "^amount_type_invalid$"):
                    validate_amount_cents(value, min_cents=0, max_cents=100000)

    def test_out_of_range_and_negative_rejected_by_explicit_limits(self):
        for value in (-1, 100001, 10**100):
            with self.subTest(value=value):
                with self.assertRaisesRegex(QuestionnaireValidationError, "^amount_out_of_range$"):
                    validate_amount_cents(value, min_cents=0, max_cents=100000)
        self.assertEqual(validate_amount_cents(-25, min_cents=-100, max_cents=100), -25)

    def test_strict_calendar_date_and_ordered_flow(self):
        row = validate_flow(
            amount_cents=12500, period_start="2026-01-01", period_end="2026-12-31",
            min_cents=0, max_cents=100000,
        )
        self.assertEqual((row.amount_cents, row.period_start, row.period_end),
                         (12500, date(2026, 1, 1), date(2026, 12, 31)))
        self.assertNotIn("12500", repr(row))
        with self.assertRaises(FrozenInstanceError):
            row.amount_cents = 99

    def test_same_day_flow_is_permitted_without_annualization(self):
        row = validate_flow(
            amount_cents=1, period_start="2026-03-31", period_end="2026-03-31",
            min_cents=0, max_cents=100,
        )
        self.assertEqual(row.period_start, row.period_end)

    def test_inverted_flow_period_fails_without_echoing_financial_inputs(self):
        with self.assertRaises(QuestionnaireValidationError) as context:
            validate_flow(
                amount_cents=12345, period_start="2026-12-31", period_end="2026-01-01",
                min_cents=0, max_cents=100000,
            )
        self.assertEqual(str(context.exception), "flow_period_inverted")

    def test_invalid_iso_dates_never_parse_or_normalize(self):
        for bad in (
            None, 20260101, date(2026, 1, 1), "2026-1-01", "2026-01-1",
            "2026-02-30", "2026-13-01", "2026-00-10",
            "2026-01-01T00:00:00Z", "2026-01-01 ", " 2026-01-01",
            "2026/01/01", "2026-01-01\n", False,
        ):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(QuestionnaireValidationError, "^date_invalid$"):
                    validate_balance(
                        balance_cents=12345, as_of_date=bad,
                        min_cents=0, max_cents=100000,
                    )

    def test_calendar_year_flow_requires_explicit_selected_year(self):
        row = validate_calendar_year_flow(
            reporting_year=2026, amount_cents=12500,
            period_start="2026-02-01", period_end="2026-02-28",
            min_cents=0, max_cents=100000,
        )
        self.assertEqual((row.period_start.year, row.period_end.year), (2026, 2026))
        self.assertEqual(row.amount_cents, 12500)
        self.assertNotIn("12500", repr(row))

    def test_reporting_year_invalid_without_explicit_integer(self):
        for invalid in (None, True, False, 0, 10000, "2026", 2026.0, [], {}):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(
                    QuestionnaireValidationError, "^reporting_year_invalid$"
                ):
                    validate_calendar_year_flow(
                        reporting_year=invalid, amount_cents=100,
                        period_start="2026-01-01", period_end="2026-12-31",
                        min_cents=0, max_cents=100000,
                    )

    def test_cross_year_and_wrong_year_flows_fail_closed(self):
        for start, end in (
            ("2025-12-31", "2026-01-01"),
            ("2026-12-31", "2027-01-01"),
            ("2025-01-01", "2025-12-31"),
        ):
            with self.subTest(start=start, end=end):
                with self.assertRaisesRegex(
                    QuestionnaireValidationError, "^flow_outside_reporting_year$"
                ):
                    validate_calendar_year_flow(
                        reporting_year=2026, amount_cents=100,
                        period_start=start, period_end=end,
                        min_cents=0, max_cents=100000,
                    )

    def test_calendar_flow_preserves_existing_money_date_guards(self):
        for value, start, end, code in (
            ("100", "2026-01-01", "2026-01-01", "amount_type_invalid"),
            (-1, "2026-01-01", "2026-01-01", "amount_out_of_range"),
            (100, "2026-02-30", "2026-03-01", "date_invalid"),
            (100, "2026-04-02", "2026-04-01", "flow_period_inverted"),
        ):
            with self.subTest(code=code):
                with self.assertRaisesRegex(
                    QuestionnaireValidationError, "^" + code + "$"
                ):
                    validate_calendar_year_flow(
                        reporting_year=2026, amount_cents=value,
                        period_start=start, period_end=end,
                        min_cents=0, max_cents=100000,
                    )

    def test_balance_is_not_flow_or_annualized(self):
        row = validate_balance(
            balance_cents=76543, as_of_date="2026-07-01",
            min_cents=0, max_cents=100000,
        )
        self.assertEqual((row.balance_cents, row.as_of_date), (76543, date(2026, 7, 1)))
        self.assertFalse(hasattr(row, "period_start"))
        self.assertFalse(hasattr(row, "annual_amount_cents"))
        self.assertNotIn("76543", repr(row))
        with self.assertRaises(FrozenInstanceError):
            row.balance_cents = 0

    def test_typed_question_boolean_keeps_no_distinct_from_yes(self):
        self.assertIs(
            validate_typed_question_answer(value=False, answer_type="boolean"),
            False,
        )
        self.assertIs(
            validate_typed_question_answer(value=True, answer_type="boolean"),
            True,
        )

    def test_typed_question_boolean_rejects_missing_and_coercion(self):
        for bad in (None, 0, 1, "false", "true", [], {}, (False,)):
            with self.subTest(value=bad):
                with self.assertRaisesRegex(
                    QuestionnaireValidationError, "^question_answer_type_invalid$"
                ):
                    validate_typed_question_answer(
                        value=bad, answer_type="boolean",
                    )

    def test_typed_question_enum_requires_exact_trusted_options(self):
        options = ("CHOICE_A", "CHOICE_B")
        self.assertEqual(
            validate_typed_question_answer(
                value="CHOICE_A", answer_type="enum", enum_options=options,
            ),
            "CHOICE_A",
        )
        for value in ("choice_a", "CHOICE_A ", "SYNTHETIC_PRIVATE_VALUE"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    QuestionnaireValidationError, "^question_answer_not_allowed$"
                ) as error:
                    validate_typed_question_answer(
                        value=value, answer_type="enum", enum_options=options,
                    )
                self.assertNotIn(value, str(error.exception))
        for value in (None, False, True, 1, [], {}, ["CHOICE_A"]):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    QuestionnaireValidationError, "^question_answer_type_invalid$"
                ):
                    validate_typed_question_answer(
                        value=value, answer_type="enum", enum_options=options,
                    )

    def test_typed_question_definition_must_be_explicit_and_unique(self):
        for options in (None, (), [], ["CHOICE_A"], (1,), (True,),
                        ("",), (" CHOICE_A",), ("CHOICE_A ",),
                        ("CHOICE_A", "CHOICE_A")):
            with self.subTest(options=options):
                with self.assertRaisesRegex(
                    QuestionnaireValidationError, "^question_definition_invalid$"
                ):
                    validate_typed_question_answer(
                        value="CHOICE_A", answer_type="enum",
                        enum_options=options,
                    )
        with self.assertRaisesRegex(
            QuestionnaireValidationError, "^question_definition_invalid$"
        ):
            validate_typed_question_answer(
                value=False, answer_type="boolean", enum_options=("ANY",),
            )

    def test_typed_question_rejects_unapproved_free_text_or_json_types(self):
        for answer_type in (
            None, True, "", "text", "json", "number", "money",
            "boolean ", [], {},
        ):
            with self.subTest(answer_type=answer_type):
                with self.assertRaisesRegex(
                    QuestionnaireValidationError, "^question_type_unsupported$"
                ):
                    validate_typed_question_answer(
                        value={"private": "never-accept"},
                        answer_type=answer_type,
                    )

    def test_consent_distinguishes_unknown_no_and_yes(self):
        self.assertIsNone(validate_optional_consent(None))
        self.assertIs(validate_optional_consent(False), False)
        self.assertIs(validate_optional_consent(True), True)
        for bad in (0, 1, "", "false", "true", [], {}, [True]):
            with self.subTest(value=bad):
                with self.assertRaisesRegex(QuestionnaireValidationError, "^consent_type_invalid$"):
                    validate_optional_consent(bad)

    def test_error_messages_contain_only_stable_codes(self):
        secret = "SYNTHETIC_HOUSEHOLD_INCOME_SECRET"
        try:
            validate_amount_cents(secret, min_cents=0, max_cents=100000)
        except QuestionnaireValidationError as exc:
            self.assertEqual(str(exc), "amount_type_invalid")
            self.assertNotIn(secret, str(exc))
        else:
            self.fail("Unapproved string financial input accepted")


if __name__ == "__main__":
    unittest.main()
