"""Synthetic-only offer contract tests. No database, offers or production routing."""
import unittest
from dataclasses import FrozenInstanceError

from jireh.financial_aid.buckets import AidBucket
from jireh.financial_aid.offer_contract import OfferContractError, validate_officer_offer_intent


VALID = {
    "director_authorized": True,
    "application_in_authorized_school_year": True,
    "application_status": "SUBMITTED",
    "student_selected_for_application": True,
    "application_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "student_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    "bucket": "need",
    "amount_cents": 25_000,
    "min_cents": 1,
    "max_cents": 100_000,
}


class SyntheticOfferIntentTests(unittest.TestCase):
    def assert_rejected(self, code, **changes):
        with self.assertRaises(OfferContractError) as cm:
            validate_officer_offer_intent(**(VALID | changes))
        self.assertEqual(str(cm.exception), code)

    def test_fictional_250_dollar_need_offer_intent(self):
        intent = validate_officer_offer_intent(**VALID)
        self.assertEqual(intent.amount_cents, 25_000)
        self.assertIs(intent.bucket, AidBucket.NEED)
        self.assertEqual(str(intent.application_id), VALID["application_id"])
        self.assertNotIn("25000", repr(intent))
        with self.assertRaises(FrozenInstanceError):
            intent.amount_cents = 1

    def test_no_staff_or_school_year_scope_never_passes(self):
        for value in (None, False, 1, "yes", [], {}):
            with self.subTest(value=value):
                self.assert_rejected("offer_staff_access_denied", director_authorized=value)
                self.assert_rejected(
                    "offer_application_scope_denied",
                    application_in_authorized_school_year=value,
                )

    def test_draft_and_unknown_states_cannot_be_offered(self):
        for value in (None, "DRAFT", "OFFERED", "submitted", True, 1, {}):
            with self.subTest(value=value):
                self.assert_rejected("offer_application_not_submitted", application_status=value)

    def test_foreign_or_unselected_child_cannot_be_offered(self):
        for value in (None, False, 1, "true", [], {}):
            with self.subTest(value=value):
                self.assert_rejected("offer_student_not_selected", student_selected_for_application=value)

    def test_strict_canonical_uuid_identifiers(self):
        for field in ("application_id", "student_id"):
            for value in (None, True, 7, "", "7", "not-a-uuid", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA", {}):
                with self.subTest(field=field, value=value):
                    self.assert_rejected("offer_uuid_invalid", **{field: value})

    def test_only_five_existing_buckets_are_accepted(self):
        for bucket in (None, "", "Need", "scholarship", True, 1, {}, []):
            with self.subTest(bucket=bucket):
                self.assert_rejected("offer_bucket_invalid", bucket=bucket)
        for aid_bucket in AidBucket:
            intent = validate_officer_offer_intent(**(VALID | {"bucket": aid_bucket.value}))
            self.assertIs(intent.bucket, aid_bucket)

    def test_bounds_are_explicit_and_money_never_coerced(self):
        for value in (None, "250.00", 250.0, True, [], {}):
            with self.subTest(value=value):
                self.assert_rejected("offer_amount_type_invalid", amount_cents=value)
        self.assert_rejected("offer_money_bounds_not_configured", min_cents=None)
        self.assert_rejected("offer_money_bounds_invalid", min_cents=101, max_cents=100)
        self.assert_rejected("offer_amount_out_of_range", amount_cents=100_001)
        self.assert_rejected("offer_amount_out_of_range", amount_cents=-1)
        self.assert_rejected("offer_amount_not_positive", amount_cents=0, min_cents=0)
        self.assert_rejected("offer_amount_out_of_range", amount_cents=25_000, max_cents=24_999)

    def test_error_codes_never_echo_sensitive_values(self):
        private_value = "SYNTHETIC_PRIVATE_CHILD_NAME"
        with self.assertRaises(OfferContractError) as cm:
            validate_officer_offer_intent(**(VALID | {"bucket": private_value}))
        self.assertEqual(str(cm.exception), "offer_bucket_invalid")
        self.assertNotIn(private_value, str(cm.exception))


if __name__ == "__main__":
    unittest.main()
