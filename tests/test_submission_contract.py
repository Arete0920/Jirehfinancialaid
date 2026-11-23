"""Pure synthetic tests only: no database, real family or live submission."""

import unittest
from dataclasses import FrozenInstanceError

from jireh.financial_aid.submission_contract import (
    ApplicationState,
    SubmissionContractError,
    validate_submission_intent,
)


VALID = {
    "current_state": "DRAFT",
    "accuracy_attested": True,
    "consent_version": "synthetic-disclosure-v1",
    "disclosure_is_approved": True,
    "questionnaire_is_complete": True,
    "authorized_household_scope": True,
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

    def assert_error(self, error, **overrides):
        with self.assertRaises(SubmissionContractError) as cm:
            validate_submission_intent(**(VALID | overrides))
        self.assertEqual(str(cm.exception), error)


if __name__ == "__main__":
    unittest.main()
