"""Provider-neutral fee quotation contract; no collection, status, or identity grants."""
import unittest
from uuid import UUID

from jireh.financial_aid.fees import (
    APPLICATION_FEE_PAYER,
    HOUSEHOLD_APPLICATION_FEE_CENTS,
    quote_application_submission_fee,
    FeeObligationError,
)

SCHOOL = UUID("11111111-1111-4111-8111-111111111111")
HOUSEHOLD = UUID("22222222-2222-4222-8222-222222222222")
YEAR = UUID("33333333-3333-4333-8333-333333333333")
APPLICATION = UUID("44444444-4444-4444-8444-444444444444")
OTHER_APPLICATION = UUID("55555555-5555-4555-8555-555555555555")


def quote(**override):
    fields = {
        "application_id": APPLICATION,
        "school_id": SCHOOL,
        "household_id": HOUSEHOLD,
        "academic_year_id": YEAR,
    }
    fields.update(override)
    return quote_application_submission_fee(**fields)


class ApplicationFeeObligationTests(unittest.TestCase):
    def test_quote_is_exactly_one_household_fee_at_submission(self):
        quote_result = quote()
        self.assertEqual(quote_result.amount_cents, 5_500)
        self.assertEqual(quote_result.currency, "USD")
        self.assertEqual(quote_result.payer, APPLICATION_FEE_PAYER)
        self.assertEqual(quote_result.charge_point, "submission")
        self.assertEqual(quote_result.scope, "household_application")
        self.assertEqual(quote_result.application_id, APPLICATION)
        self.assertEqual(quote_result.household_id, HOUSEHOLD)
        self.assertFalse(hasattr(quote_result, "paid"))
        self.assertFalse(hasattr(quote_result, "provider_transaction_id"))

    def test_retries_quote_same_obligation_without_creating_payment(self):
        one = quote()
        again = quote()
        self.assertEqual(one, again)
        self.assertEqual(one.obligation_key, again.obligation_key)
        self.assertTrue(one.obligation_key.startswith("jireh:household-application-fee:v1:"))

    def test_different_application_has_different_obligation_identity(self):
        self.assertNotEqual(quote().obligation_key, quote(application_id=OTHER_APPLICATION).obligation_key)

    def test_single_fee_does_not_depend_on_student_count(self):
        # Deliberately no student_count or per-child amount parameter.
        result = quote()
        self.assertFalse(hasattr(result, "student_count"))
        with self.assertRaises(TypeError):
            quote(student_count=3)

    def test_malformed_scope_fails_closed(self):
        for field in ("application_id", "school_id", "household_id", "academic_year_id"):
            for invalid in (None, "", "../other", 99, UUID(int=0)):
                with self.subTest(field=field, invalid=str(invalid)):
                    with self.assertRaises(FeeObligationError):
                        quote(**{field: invalid})

    def test_existing_fee_constants_remain_stable(self):
        self.assertEqual(HOUSEHOLD_APPLICATION_FEE_CENTS, 5500)
        self.assertEqual(APPLICATION_FEE_PAYER, "family")


if __name__ == "__main__":
    unittest.main()
