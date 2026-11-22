"""Full synthetic cryptographic MFA acceptance for initial director grants.

No real schools, live operator identities, production credentials, HTTP routes
or customer data. This suite verifies two DISTINCT approved FIDO2 keys and
transactional action-bound proof consumption on SQLite and PostgreSQL.
"""

import hashlib
from datetime import timedelta
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.test import TransactionTestCase
from django.utils import timezone
from fido2.cose import ES256
from fido2.utils import sha256
from fido2.webauthn import (
    AttestedCredentialData, AuthenticationResponse,
    AuthenticatorAssertionResponse, AuthenticatorData, CollectedClientData,
)

from .first_director_bootstrap import propose_first_director, approve_first_director
from .models import (
    OperatorWebAuthnCredential, OperatorWebAuthnActionIntent,
    OperatorWebAuthnEnrollmentApproval, OperatorWebAuthnRegistration,
    OperatorWebAuthnPossessionChallenge,
    FirstDirectorBootstrapRequest, School, SchoolStaffAccess,
    SchoolGrantDecisionEvent,
)
from .operator_webauthn_actions import (
    begin_director_action_proof, complete_director_action_proof,
)
from .operator_webauthn_registry import revoke_registered_operator_credential
from .password_recovery import enroll_verified_recovery_contact
from .redemption import issue_mailbox_challenge
from .test_operator_webauthn_registry import (
    OperatorCredentialRegistryTests, RP, ORIGIN, CREDENTIAL_ID, PASSWORD,
)


REFERENCE = "SCHOOL-AUTHORIZATION-2026-001"


class FirstDirectorWithWebAuthnTests(TransactionTestCase):
    def setUp(self):
        OperatorCredentialRegistryTests.setUp(self)
        flags = self.settings(
            JIREH_FIRST_DIRECTOR_BOOTSTRAP_ENABLED=True,
            JIREH_OPERATOR_ACTION_MFA_ENABLED=True,
        )
        flags.enable()
        self.addCleanup(flags.disable)
        self.school = School.objects.create(
            code="mfa-bootstrap-school", name="Synthetic MFA School",
        )
        self.second_school = School.objects.create(
            code="other-mfa-bootstrap-school", name="Other Synthetic MFA School",
        )
        self.subject = get_user_model().objects.create_user(
            username="mfa-director-subject",
            password="Synthetic-Only-Director-Password-2026!",
        )
        _, token = issue_mailbox_challenge(
            user=self.subject, email="mfa-subject@example.invalid",
        )
        enroll_verified_recovery_contact(
            user=self.subject, email="mfa-subject@example.invalid",
            mailbox_token=token,
        )
        self.second_key = ec.generate_private_key(ec.SECP256R1())
        self.second_key_id = b"synthetic-second-mfa-operator-key-2026"
        self.second_digest = hashlib.sha256(self.second_key_id).hexdigest()
        second_data = bytes(AttestedCredentialData.create(
            b"\x00" * 16, self.second_key_id,
            ES256.from_cryptography_key(self.second_key.public_key()),
        ))
        cred = OperatorWebAuthnCredential.objects.create(
            operator=self.second, credential_id_digest=self.second_digest,
            credential_data=second_data, rp_id=RP, origin=ORIGIN,
        )
        now = timezone.now()
        registration = OperatorWebAuthnRegistration.objects.create(
            operator=self.second, rp_id=RP, origin=ORIGIN,
            challenge="synthetic-second-registration-for-mfa",
            expires_at=now + timedelta(minutes=5), closed_at=now,
            credential_id_digest=self.second_digest,
        )
        possession = OperatorWebAuthnPossessionChallenge.objects.create(
            operator=self.second, credential=cred,
            challenge="synthetic-second-possession-for-mfa",
            expires_at=now + timedelta(minutes=5),
            closed_at=now, verified_at=now, verified_sign_count=0,
        )
        OperatorWebAuthnEnrollmentApproval.objects.create(
            operator=self.second, approver=self.operator,
            credential=cred, registration=registration,
            possession_proof=possession,
            approver_role=OperatorWebAuthnEnrollmentApproval.ROLE_OWNER,
            identity_verification_reference="SYNTHETIC-SECOND-OPERATOR-APPROVAL",
            approved_at=now,
        )
        cred.enrollment_verified_at = now
        cred.save(update_fields=["enrollment_verified_at", "updated_at"])

    def signed(self, options, *, key, credential_id, count=1):
        client = CollectedClientData.create(
            CollectedClientData.TYPE.GET, options.public_key.challenge, ORIGIN,
        )
        authenticator = AuthenticatorData.create(
            sha256(RP.encode()),
            AuthenticatorData.FLAG.UP | AuthenticatorData.FLAG.UV,
            count,
        )
        signature = key.sign(
            bytes(authenticator) + client.hash,
            ec.ECDSA(hashes.SHA256()),
        )
        return AuthenticationResponse(
            raw_id=credential_id,
            response=AuthenticatorAssertionResponse(
                client_data=client, authenticator_data=authenticator,
                signature=signature,
            ),
        )

    def proof(self, *, actor, action, reference=REFERENCE,
              school_id=None, subject_user_id=None, request_id=None):
        is_first = actor.pk == self.operator.pk
        options, intent_id = begin_director_action_proof(
            operator=actor,
            credential_id_digest=self.digest if is_first else self.second_digest,
            action=action, authorization_reference=reference,
            school_id=school_id, subject_user_id=subject_user_id,
            request_id=request_id,
        )
        self.assertEqual(
            complete_director_action_proof(
                operator=actor, intent_id=intent_id,
                response=self.signed(
                    options,
                    key=self.key if is_first else self.second_key,
                    credential_id=CREDENTIAL_ID if is_first else self.second_key_id,
                ),
            ), 1,
        )
        return intent_id

    def proposal_proof(self, *, school=None):
        return self.proof(
            actor=self.operator,
            action=OperatorWebAuthnActionIntent.ACTION_DIRECTOR_PROPOSE,
            school_id=(school or self.school).pk,
            subject_user_id=self.subject.pk,
        )

    def propose(self, *, mfa_intent_id=None, school=None, password=PASSWORD):
        return propose_first_director(
            operator=self.operator, operator_password=password,
            school_id=(school or self.school).pk,
            subject_user_id=self.subject.pk,
            authorization_reference=REFERENCE, mfa_intent_id=mfa_intent_id,
        )

    def approval_proof(self, request_id):
        return self.proof(
            actor=self.second,
            action=OperatorWebAuthnActionIntent.ACTION_DIRECTOR_APPROVE,
            request_id=request_id,
        )

    def approve(self, proposal, *, mfa_intent_id):
        return approve_first_director(
            operator=self.second, operator_password=PASSWORD,
            request_id=proposal.pk, authorization_reference=REFERENCE,
            mfa_intent_id=mfa_intent_id,
        )

    def test_two_distinct_real_crypto_assertions_required_for_grant(self):
        proposal_intent = self.proposal_proof()
        proposal = self.propose(mfa_intent_id=proposal_intent)
        self.assertEqual(FirstDirectorBootstrapRequest.objects.count(), 1)
        self.assertFalse(SchoolStaffAccess.objects.exists())
        approval_intent = self.approval_proof(proposal.pk)
        grant = self.approve(proposal, mfa_intent_id=approval_intent)
        self.assertEqual(grant.user_id, self.subject.pk)
        self.assertEqual(grant.school_id, self.school.pk)
        self.assertEqual(SchoolGrantDecisionEvent.objects.count(), 1)
        self.assertIsNotNone(
            OperatorWebAuthnActionIntent.objects.get(
                pk=proposal_intent,
            ).consumed_at
        )
        self.assertIsNotNone(
            OperatorWebAuthnActionIntent.objects.get(
                pk=approval_intent,
            ).consumed_at
        )

    def test_missing_mfa_cannot_propose_even_with_password_and_flag(self):
        with self.assertRaises(PermissionDenied):
            self.propose()
        self.assertFalse(FirstDirectorBootstrapRequest.objects.exists())
        self.assertFalse(SchoolStaffAccess.objects.exists())

    def test_wrong_school_proof_fails_and_cannot_create_proposal(self):
        proof_id = self.proposal_proof()
        with self.assertRaises(PermissionDenied):
            self.propose(mfa_intent_id=proof_id, school=self.second_school)
        self.assertFalse(FirstDirectorBootstrapRequest.objects.exists())
        self.assertIsNone(
            OperatorWebAuthnActionIntent.objects.get(pk=proof_id).consumed_at
        )
        self.propose(mfa_intent_id=proof_id)

    def test_proposer_mfa_cannot_substitute_for_approval_proof(self):
        proposal = self.propose(mfa_intent_id=self.proposal_proof())
        with self.assertRaises(PermissionDenied):
            self.approve(proposal, mfa_intent_id=None)
        self.assertFalse(SchoolStaffAccess.objects.exists())
        self.approve(proposal, mfa_intent_id=self.approval_proof(proposal.pk))

    def test_revoked_key_after_verification_prevents_proposal(self):
        proof_id = self.proposal_proof()
        revoke_registered_operator_credential(
            operator=self.operator, credential_id_digest=self.digest,
        )
        with self.assertRaises(PermissionDenied):
            self.propose(mfa_intent_id=proof_id)
        self.assertFalse(FirstDirectorBootstrapRequest.objects.exists())

    def test_wrong_password_does_not_spend_verified_mfa_proof(self):
        proof_id = self.proposal_proof()
        with self.assertRaises(PermissionDenied):
            self.propose(mfa_intent_id=proof_id, password="invalid")
        self.assertIsNone(
            OperatorWebAuthnActionIntent.objects.get(pk=proof_id).consumed_at
        )
        self.propose(mfa_intent_id=proof_id)

    def test_audit_outage_rolls_back_grant_and_mfa_consumption(self):
        proposal = self.propose(mfa_intent_id=self.proposal_proof())
        proof_id = self.approval_proof(proposal.pk)
        with patch.object(
            SchoolGrantDecisionEvent.objects, "create",
            side_effect=RuntimeError("synthetic downstream audit failure"),
        ):
            with self.assertRaisesMessage(RuntimeError, "synthetic downstream audit failure"):
                self.approve(proposal, mfa_intent_id=proof_id)
        self.assertFalse(SchoolStaffAccess.objects.exists())
        self.assertIsNone(
            OperatorWebAuthnActionIntent.objects.get(pk=proof_id).consumed_at
        )
        self.approve(proposal, mfa_intent_id=proof_id)

    def test_action_evidence_feature_disabled_denies_initial_director(self):
        proof_id = self.proposal_proof()
        with self.settings(JIREH_OPERATOR_ACTION_MFA_ENABLED=False):
            with self.assertRaises(PermissionDenied):
                self.propose(mfa_intent_id=proof_id)
        self.assertFalse(FirstDirectorBootstrapRequest.objects.exists())
