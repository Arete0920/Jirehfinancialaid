"""Pure synthetic tests only: no database, real family or live submission."""

import unittest
from dataclasses import FrozenInstanceError, replace
from uuid import UUID

from jireh.financial_aid.fees import quote_application_submission_fee

from jireh.financial_aid.submission_contract import (
    ApplicationState,
    SubmissionContractError,
    OfflinePaymentReconciliation,
    validate_submission_intent,
)


SCHOOL = UUID("11111111-1111-4111-8111-111111111111")
HOUSEHOLD = UUID("22222222-2222-4222-8222-222222222222")
YEAR = UUID("33333333-3333-4333-8333-333333333333")
APPLICATION = UUID("44444444-4444-4444-8444-444444444444")
RECEIPT = UUID("55555555-5555-4555-8555-555555555555")
OBLIGATION = quote_application_submission_fee(
    application_id=APPLICATION, school_id=SCHOOL,
    household_id=HOUSEHOLD, academic_year_id=YEAR,
)


def reconciled_fee(**changes):
    payment = OfflinePaymentReconciliation(
        application_id=APPLICATION,
        school_id=SCHOOL,
        household_id=HOUSEHOLD,
        academic_year_id=YEAR,
        obligation_key=OBLIGATION.obligation_key,
        amount_cents=5_500,
        currency="USD",
        receipt_id=RECEIPT,
        terminal_success=True,
        source_authenticated=True,
        durably_reconciled=True,
    )
    return replace(payment, **changes)


VALID = {
    "current_state": "DRAFT",
    "accuracy_attested": True,
    "consent_version": "synthetic-disclosure-v1",
    "disclosure_is_approved": True,
    "questionnaire_is_complete": True,
    "authorized_household_scope": True,
    "fee_obligation": OBLIGATION,
    "payment_reconciliation": reconciled_fee(),
}


class SubmissionContractTests(unittest.TestCase):
    def test_only_draft_to_submitted_intent_and_explicit_retry(self):
        first = validate_submission_intent(**VALID)
        self.assertIs(first.desired_state, ApplicationState.SUBMITTED)
        self.assertEqual(first.consent_version, "synthetic-disclosure-v1")
        self.assertFalse(first.is_retry)
        retry = validate_submission_intent(**(VALID | {"current_state": "SUBMITTED"}))
        self.assertIs(retry.desired_state, ApplicationState.SUBMITTED)
        self.assertTrue(retry.is_retry)
        with self.assertRaises(FrozenInstanceError):
            first.consent_version = "altered"
        self.assertNotIn("synthetic-disclosure-v1", repr(first))

    def test_missing_or_other_lifecycle_states_fail_closed(self):
        for state in (None, "", "draft", "submitted", "REOPENED", "WITHDRAWN", "APPROVED", 1, True, {}, []):
            with self.subTest(state=state):
                self.assert_error("submission_state_invalid", current_state=state)

    def test_attestation_is_explicit_true_only(self):
        for value in (None, False, 1, "true", "yes", {}, []):
            with self.subTest(value=value):
                self.assert_error("submission_attestation_required", accuracy_attested=value)

    def test_disclosure_and_version_are_trusted_and_required(self):
        for value in (None, False, 1, "true", [], {}):
            self.assert_error("submission_disclosure_not_approved", disclosure_is_approved=value)
        for version in (None, "", " ", " v1", "v1 ", True, 1, [], {}, "x" * 65):
            with self.subTest(version=version):
                self.assert_error("submission_consent_version_invalid", consent_version=version)

    def test_authorization_and_completeness_fail_closed(self):
        for value in (None, False, 1, "yes", [], {}):
            self.assert_error("submission_access_denied", authorized_household_scope=value)
            self.assert_error("submission_incomplete", questionnaire_is_complete=value)

    def test_error_does_not_disclose_any_financial_or_personal_inputs(self):
        secret = "SYNTHETIC_PRIVATE_STUDENT_NAME"
        with self.assertRaises(SubmissionContractError) as cm:
            validate_submission_intent(**(VALID | {"consent_version": secret + " "}))
        self.assertEqual(str(cm.exception), "submission_consent_version_invalid")
        self.assertNotIn(secret, str(cm.exception))


    def test_missing_or_untrusted_offline_payment_never_submits(self):
        for value in (
            None, False, True, "paid", {"paid": True}, {}, [],
            reconciled_fee(terminal_success=False),
            reconciled_fee(source_authenticated=False),
            reconciled_fee(durably_reconciled=False),
            reconciled_fee(receipt_id=UUID(int=0)),
            reconciled_fee(receipt_id="payment-ref"),
        ):
            with self.subTest(value_type=type(value).__name__), self.assertRaisesRegex(
                SubmissionContractError, "^submission_payment_unreconciled$"
            ):
                validate_submission_intent(**(VALID | {"payment_reconciliation": value}))

    def test_fee_must_match_canonical_application_obligation(self):
        for obligation in (
            None, {}, True, replace(OBLIGATION, amount_cents=0),
            replace(OBLIGATION, currency="EUR"),
            replace(OBLIGATION, obligation_key="wrong"),
            replace(OBLIGATION, household_id=UUID(int=0)),
        ):
            with self.subTest(obligation=str(type(obligation))), self.assertRaisesRegex(
                SubmissionContractError, "^submission_fee_obligation_invalid$"
            ):
                validate_submission_intent(**(VALID | {"fee_obligation": obligation}))

    def test_payment_must_match_exact_case_scope(self):
        for changed in (
            {"application_id": UUID("66666666-6666-4666-8666-666666666666")},
            {"school_id": UUID("66666666-6666-4666-8666-666666666666")},
            {"household_id": UUID("66666666-6666-4666-8666-666666666666")},
            {"academic_year_id": UUID("66666666-6666-4666-8666-666666666666")},
            {"obligation_key": "jireh:forged"},
        ):
            with self.subTest(changed=list(changed)), self.assertRaisesRegex(
                SubmissionContractError, "^submission_payment_scope_mismatch$"
            ):
                validate_submission_intent(
                    **(VALID | {"payment_reconciliation": reconciled_fee(**changed)})
                )

    def test_amount_currency_and_bool_types_fail_closed(self):
        for value in (None, False, 5_499, 5_501, "5500", 5500.0):
            with self.subTest(amount=value), self.assertRaisesRegex(
                SubmissionContractError, "^submission_payment_amount_mismatch$"
            ):
                validate_submission_intent(
                    **(VALID | {"payment_reconciliation": reconciled_fee(amount_cents=value)})
                )
        for value in (None, 1, "EUR", "usd"):
            with self.subTest(currency=value), self.assertRaisesRegex(
                SubmissionContractError, "^submission_payment_currency_mismatch$"
            ):
                validate_submission_intent(
                    **(VALID | {"payment_reconciliation": reconciled_fee(currency=value)})
                )
        for key in ("terminal_success", "source_authenticated", "durably_reconciled"):
            for value in (1, "true", None):
                with self.subTest(key=key, value=value), self.assertRaisesRegex(
                    SubmissionContractError, "^submission_payment_unreconciled$"
                ):
                    validate_submission_intent(
                        **(VALID | {"payment_reconciliation": reconciled_fee(**{key: value})})
                    )

    def test_submitted_retry_requires_same_reconciled_obligation(self):
        result = validate_submission_intent(
            **(VALID | {"current_state": "SUBMITTED"})
        )
        self.assertTrue(result.is_retry)
        self.assertIs(result.desired_state, ApplicationState.SUBMITTED)
        with self.assertRaisesRegex(
            SubmissionContractError, "^submission_payment_unreconciled$"
        ):
            validate_submission_intent(
                **(VALID | {
                    "current_state": "SUBMITTED",
                    "payment_reconciliation": reconciled_fee(durably_reconciled=False),
                })
            )

    def test_reconciliation_is_only_offline_evidence_never_provider_approval(self):
        result = validate_submission_intent(**VALID)
        self.assertFalse(result.is_retry)
        self.assertNotIn(str(RECEIPT), repr(result))
        self.assertNotIn("5500", repr(result))
        with self.assertRaises(FrozenInstanceError):
            VALID["payment_reconciliation"].terminal_success = False

    def assert_error(self, error, **overrides):
        with self.assertRaises(SubmissionContractError) as cm:
            validate_submission_intent(**(VALID | overrides))
        self.assertEqual(str(cm.exception), error)


if __name__ == "__main__":
    unittest.main()
