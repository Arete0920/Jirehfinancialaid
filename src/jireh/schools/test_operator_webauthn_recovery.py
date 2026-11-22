"""Synthetic-only loss and recovery contracts. No real operator accounts."""

import hashlib
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone
from fido2.cose import ES256
from fido2.utils import sha256
from fido2.webauthn import (
    AttestationObject, AttestedCredentialData, AuthenticatorAttestationResponse,
    AuthenticatorAssertionResponse, AuthenticationResponse, AuthenticatorData,
    CollectedClientData, RegistrationResponse,
)

from .models import (
    LoginAttemptBudget, OperatorWebAuthnCredential, OperatorWebAuthnRecovery,
    OperatorWebAuthnRecoveryReplacement,
)
from .operator_webauthn_approval import approve_pending_operator_credential
from .operator_webauthn_recovery import (
    confirm_recovery_replacement, revoke_lost_operator_credential,
)
from .operator_webauthn_registration import (
    begin_operator_registration, complete_operator_registration,
)
from .operator_webauthn_possession import (
    begin_pending_key_proof, complete_pending_key_proof,
)
from .operator_webauthn_registry import begin_registered_operator_challenge
from .test_operator_webauthn_approval import OperatorEnrollmentApprovalTests


PASSWORD = "Synthetic-Only-Possession-Operator-2026!"
RP = "auth.jireh.example.invalid"
ORIGIN = "https://" + RP
REF = "INDEPENDENT-RECOVERY-VERIFIED-2026-001"
REPLACEMENT_REF = "INDEPENDENT-REPLACEMENT-VERIFIED-2026-002"


class OperatorWebAuthnRecoveryTests(TransactionTestCase):
    # Use existing cryptographic registration and proof fixture but do not
    # inherit its test methods or change its independent test behavior.
    proof_api = OperatorEnrollmentApprovalTests.proof_api
    begin = OperatorEnrollmentApprovalTests.begin
    complete = OperatorEnrollmentApprovalTests.complete
    assertion = OperatorEnrollmentApprovalTests.assertion
    prove = OperatorEnrollmentApprovalTests.prove
    approve = OperatorEnrollmentApprovalTests.approve

    def setUp(self):
        OperatorEnrollmentApprovalTests.setUp(self)
        guard = self.settings(JIREH_OPERATOR_CREDENTIAL_RECOVERY_ENABLED=True)
        guard.enable()
        self.addCleanup(guard.disable)

    def revoke(self, **overrides):
        params = dict(
            approver=self.other,
            approver_password=PASSWORD,
            operator_id=self.operator.pk,
            credential_id_digest=self.digest,
            reason=OperatorWebAuthnRecovery.REASON_LOST,
            identity_verification_reference=REF,
        )
        params.update(overrides)
        return revoke_lost_operator_credential(**params)

    def confirm(self, recovery, digest, **overrides):
        params = dict(
            approver=self.other,
            approver_password=PASSWORD,
            recovery_id=recovery.pk,
            replacement_credential_id_digest=digest,
            confirmation_reference=REPLACEMENT_REF,
        )
        params.update(overrides)
        return confirm_recovery_replacement(**params)

    def make_new_credential(self):
        """Use a genuine synthetic FIDO2 registration and proof, not SQL forgery."""
        key = ec.generate_private_key(ec.SECP256R1())
        credential_id = b"synthetic-post-loss-replacement-key-2026"
        options, registration_id = begin_operator_registration(
            operator=self.operator, rp_id=RP, origin=ORIGIN,
        )
        client = CollectedClientData.create(
            CollectedClientData.TYPE.CREATE, options.public_key.challenge,
            ORIGIN,
        )
        attested = AttestedCredentialData.create(
            b"\x00" * 16, credential_id,
            ES256.from_cryptography_key(key.public_key()),
        )
        auth = AuthenticatorData.create(
            sha256(RP.encode()),
            AuthenticatorData.FLAG.UP | AuthenticatorData.FLAG.AT |
            AuthenticatorData.FLAG.UV, 0, credential_data=attested,
        )
        response = RegistrationResponse(
            raw_id=credential_id,
            response=AuthenticatorAttestationResponse(
                client_data=client,
                attestation_object=AttestationObject.create("none", auth, {}),
            ),
        )
        digest = complete_operator_registration(
            operator=self.operator, registration_id=registration_id,
            response=response,
        )
        options, proof_id = begin_pending_key_proof(
            operator=self.operator, credential_id_digest=digest,
        )
        client = CollectedClientData.create(
            CollectedClientData.TYPE.GET, options.public_key.challenge, ORIGIN,
        )
        auth = AuthenticatorData.create(
            sha256(RP.encode()),
            AuthenticatorData.FLAG.UP | AuthenticatorData.FLAG.UV, 1,
        )
        signature = key.sign(bytes(auth) + client.hash, ec.ECDSA(hashes.SHA256()))
        assertion = AuthenticationResponse(
            raw_id=credential_id,
            response=AuthenticatorAssertionResponse(
                client_data=client, authenticator_data=auth,
                signature=signature,
            ),
        )
        self.assertEqual(
            complete_pending_key_proof(
                operator=self.operator, proof_id=proof_id, response=assertion,
            ),
            digest,
        )
        return digest

    def test_recovery_revokes_old_credential_and_records_owner_identity(self):
        self.prove()
        self.approve()
        result = self.revoke()
        self.assertEqual(result.credential.operator_id, self.operator.pk)
        self.assertEqual(result.authorized_by_id, self.other.pk)
        self.assertEqual(result.approver_role, "OWNER")
        self.assertEqual(result.reason, "LOST")
        self.assertEqual(result.identity_verification_reference, REF)
        self.assertEqual(result.credential.revoked_at, result.authorized_at)
        self.assertIsNotNone(result.credential.enrollment_verified_at)
        with self.assertRaises(PermissionDenied):
            begin_registered_operator_challenge(
                operator=self.operator, credential_id_digest=self.digest,
            )
        with self.assertRaises(PermissionDenied):
            self.revoke()
        self.assertEqual(OperatorWebAuthnRecovery.objects.count(), 1)
        self.assertFalse(OperatorWebAuthnRecoveryReplacement.objects.exists())

    def test_manager_approved_compromise_and_disabled_operator_revoke(self):
        self.prove()
        self.approve()
        self.operator.is_active = False
        self.operator.save(update_fields=["is_active"])
        audit = self.revoke(
            approver=self.manager,
            reason=OperatorWebAuthnRecovery.REASON_COMPROMISED,
        )
        self.assertEqual(audit.approver_role, "INTEGRATION_MANAGER")
        self.assertEqual(audit.reason, "COMPROMISED")

    def test_unapproved_key_cannot_be_recovered_as_active(self):
        self.prove()
        with self.assertRaises(PermissionDenied):
            self.revoke()
        self.assertIsNone(
            OperatorWebAuthnCredential.objects.get(
                credential_id_digest=self.digest,
            ).revoked_at
        )

    def test_independence_identity_reference_and_flag_are_required(self):
        self.prove()
        self.approve()
        with self.settings(JIREH_OPERATOR_CREDENTIAL_RECOVERY_ENABLED=False):
            with self.assertRaises(PermissionDenied):
                self.revoke()
        for ref in ("", "invalid spaces", "A" * 121):
            with self.subTest(ref=ref):
                with self.assertRaises(PermissionDenied):
                    self.revoke(identity_verification_reference=ref)
        with self.settings(
            JIREH_ENROLLMENT_OWNER_USER_ID=self.operator.pk,
            JIREH_ENROLLMENT_MANAGER_USER_ID=self.manager.pk,
        ):
            with self.assertRaises(PermissionDenied):
                self.revoke(approver=self.operator)
        external = get_user_model().objects.create_superuser(
            username="unlisted-recovery-attempt",
            email="unlisted@example.invalid", password=PASSWORD,
        )
        with self.assertRaises(PermissionDenied):
            self.revoke(approver=external)
        self.assertFalse(OperatorWebAuthnRecovery.objects.exists())

    def test_bad_password_charged_even_when_recovery_fails(self):
        self.prove()
        self.approve()
        with self.assertRaises(PermissionDenied):
            self.revoke(approver_password="bad")
        self.assertEqual(
            LoginAttemptBudget.objects.filter(
                identifier_digest__isnull=False,
            ).count(), 2,
        )
        self.assertFalse(OperatorWebAuthnRecovery.objects.exists())

    def test_recovery_audit_storage_failure_rolls_back_revocation(self):
        self.prove()
        self.approve()
        with patch(
            "jireh.schools.operator_webauthn_recovery.OperatorWebAuthnRecovery.objects.create",
            side_effect=IntegrityError("synthetic recovery audit outage"),
        ):
            with self.assertRaises(PermissionDenied):
                self.revoke()
        self.assertIsNone(
            OperatorWebAuthnCredential.objects.get(
                credential_id_digest=self.digest,
            ).revoked_at
        )
        self.assertFalse(OperatorWebAuthnRecovery.objects.exists())

    def test_recovery_rejects_caller_outer_transaction(self):
        self.prove()
        self.approve()
        with transaction.atomic():
            with self.assertRaises(PermissionDenied):
                self.revoke()
        self.assertFalse(OperatorWebAuthnRecovery.objects.exists())

    def test_replacement_requires_new_key_and_ordinary_independent_approval(self):
        self.prove()
        self.approve()
        loss = self.revoke()
        with self.assertRaises(PermissionDenied):
            self.confirm(loss, self.digest)
        new_digest = self.make_new_credential()
        with self.assertRaises(PermissionDenied):
            self.confirm(loss, new_digest)
        approval = approve_pending_operator_credential(
            approver=self.manager,
            approver_password=PASSWORD,
            operator_id=self.operator.pk,
            credential_id_digest=new_digest,
            identity_verification_reference=REPLACEMENT_REF,
        )
        self.assertEqual(approval.approver_id, self.manager.pk)
        result = self.confirm(loss, new_digest)
        self.assertEqual(result.recovery_id, loss.pk)
        self.assertEqual(result.replacement_credential.credential_id_digest,
                         new_digest)
        self.assertEqual(result.confirmed_by_id, self.other.pk)
        self.assertEqual(
            OperatorWebAuthnCredential.objects.get(
                credential_id_digest=self.digest,
            ).revoked_at,
            loss.authorized_at,
        )
        with self.assertRaises(PermissionDenied):
            self.confirm(loss, new_digest)
        self.assertEqual(OperatorWebAuthnRecoveryReplacement.objects.count(), 1)

    def test_recovery_history_immutable_even_through_raw_postgres(self):
        self.prove()
        self.approve()
        loss = self.revoke()
        loss.reason = "COMPROMISED"
        with self.assertRaises(ValidationError):
            loss.save()
        with self.assertRaises(ValidationError):
            loss.delete()
        if connection.vendor != "postgresql":
            return
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OperatorWebAuthnRecovery.objects.filter(pk=loss.pk).update(
                    reason="COMPROMISED",
                )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OperatorWebAuthnRecovery.objects.filter(pk=loss.pk).delete()

    def test_replacement_confirmation_failure_does_not_activate_or_replace(self):
        self.prove()
        self.approve()
        loss = self.revoke()
        new_digest = self.make_new_credential()
        approve_pending_operator_credential(
            approver=self.manager, approver_password=PASSWORD,
            operator_id=self.operator.pk, credential_id_digest=new_digest,
            identity_verification_reference=REPLACEMENT_REF,
        )
        with patch(
            "jireh.schools.operator_webauthn_recovery."
            "OperatorWebAuthnRecoveryReplacement.objects.create",
            side_effect=DatabaseError("synthetic audit write failure"),
        ):
            with self.assertRaises(PermissionDenied):
                self.confirm(loss, new_digest)
        self.assertFalse(OperatorWebAuthnRecoveryReplacement.objects.exists())
        self.assertIsNotNone(
            OperatorWebAuthnCredential.objects.get(
                credential_id_digest=self.digest,
            ).revoked_at,
        )
