"""Negative contracts for non-persistent fictional prior-year reuse."""
import unittest
from dataclasses import replace
from uuid import uuid4

from jireh.financial_aid.prior_year_reuse_candidate import (
    AnnualScope, ReuseConsentEvidence, ReusePreflightError,
    ScopedAccessEvidence, SyntheticReusePreview, preview_prior_year_reuse,
)


def uid():
    return str(uuid4())


class PriorYearReusePreflightTests(unittest.TestCase):
    def setUp(self):
        self.actor = uid()
        self.school = uid()
        self.household = uid()
        self.source = AnnualScope(self.school, self.household, uid(), uid())
        self.target = AnnualScope(self.school, self.household, uid(), uid())
        self.source_access = ScopedAccessEvidence(self.source, self.actor, True)
        self.target_access = ScopedAccessEvidence(self.target, self.actor, True)
        self.consent = ReuseConsentEvidence(
            self.source, self.actor, "SAME_SCHOOL_PRIOR_YEAR_REUSE", "fictional-v1",
            True, False,
        )
        self.inputs = {
            "source": self.source,
            "target": self.target,
            "acting_user_id": self.actor,
            "source_access": self.source_access,
            "target_access": self.target_access,
            "consent": self.consent,
            "authorized_purpose": self.consent.purpose,
            "authorized_version": self.consent.version,
            "source_precedes_target": True,
        }

    def denied(self, code, **changes):
        with self.assertRaises(ReusePreflightError) as caught:
            preview_prior_year_reuse(**{**self.inputs, **changes})
        self.assertEqual(str(caught.exception), code)
        self.assertNotIn(self.school, str(caught.exception))
        self.assertNotIn(self.household, str(caught.exception))

    def test_valid_synthetic_evidence_has_no_write_or_live_consent(self):
        preview = preview_prior_year_reuse(**self.inputs)
        self.assertIsInstance(preview, SyntheticReusePreview)
        self.assertEqual(preview.source_provenance, "PRIOR_YEAR")
        self.assertTrue(preview.copied_items_must_be_unverified)
        self.assertFalse(preview.current_year_attestation_satisfied)
        self.assertFalse(preview.production_reuse_authorized)
        self.assertFalse(preview.data_written)

    def test_cross_school_and_household_are_denied(self):
        for scope in (
            replace(self.target, school_id=uid()),
            replace(self.target, household_id=uid()),
        ):
            with self.subTest(scope=scope):
                self.denied("reuse_cross_scope_denied", target=scope)

    def test_same_period_or_application_replay_is_denied(self):
        self.denied("reuse_same_period_denied", target=replace(
            self.target, academic_year_id=self.source.academic_year_id))
        self.denied("reuse_same_period_denied", target=replace(
            self.target, application_id=self.source.application_id))
        self.denied("reuse_chronology_unverified", source_precedes_target=False)
        self.denied("reuse_chronology_unverified", source_precedes_target=None)

    def test_missing_revoked_wrong_actor_or_wrong_scope_grant_denied(self):
        for changes in (
            {"source_access": None},
            {"source_access": replace(self.source_access, active=False)},
            {"target_access": replace(self.target_access, active=False)},
            {"source_access": replace(self.source_access, actor_id=uid())},
            {"target_access": replace(self.target_access, actor_id=uid())},
            {"target_access": replace(self.target_access, scope=self.source)},
            {"source_access": replace(self.source_access, active=1)},
        ):
            with self.subTest(changes=changes):
                self.denied("reuse_access_denied", **changes)

    def test_consent_requires_matching_actor_source_purpose_version(self):
        for consent in (
            None,
            replace(self.consent, accepted=False),
            replace(self.consent, withdrawn=True),
            replace(self.consent, actor_id=uid()),
            replace(self.consent, source_scope=self.target),
            replace(self.consent, purpose="UNRELATED"),
            replace(self.consent, version="other-version"),
            replace(self.consent, accepted=1),
        ):
            with self.subTest(consent=consent):
                self.denied("reuse_consent_denied", consent=consent)

    def test_missing_approved_purpose_or_version_denied(self):
        for value in ("", None, " ", "\n", True):
            with self.subTest(value=value):
                self.denied("reuse_policy_missing", authorized_purpose=value)
                self.denied("reuse_policy_missing", authorized_version=value)

    def test_noncanonical_and_nil_identifiers_denied(self):
        for actor in (None, "bad", self.actor.upper(), str(uuid4()).replace("-", ""),
                      "00000000-0000-0000-0000-000000000000"):
            with self.subTest(actor=actor):
                self.denied("reuse_scope_invalid", acting_user_id=actor)
        self.denied("reuse_scope_invalid", target=replace(self.target, school_id="invalid"))
        self.denied("reuse_scope_invalid", source={"school_id": self.school})

    def test_no_automatic_authorization_from_prior_year(self):
        preview = preview_prior_year_reuse(**self.inputs)
        self.assertFalse(preview.current_year_attestation_satisfied)
        self.assertFalse(preview.production_reuse_authorized)

    def test_client_flags_cannot_satisfy_explicit_true_contracts(self):
        self.denied("reuse_chronology_unverified", source_precedes_target=1)
        self.denied("reuse_access_denied", target_access=replace(
            self.target_access, active="true"))
        self.denied("reuse_consent_denied", consent=replace(
            self.consent, withdrawn=0))


if __name__ == "__main__":
    unittest.main()
