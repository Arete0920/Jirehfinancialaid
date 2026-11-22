"""Synthetic PostgreSQL/SQLite transaction contracts for the operator registry.

Synthetic, locally generated EC keys; no real identities, public routes,
production provisioning or real operator credential enrollment.
"""

import hashlib
from datetime import timedelta
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone
from fido2.cose import ES256
from fido2.utils import sha256
from fido2.webauthn import (
    AttestedCredentialData,
    AuthenticationResponse,
    AuthenticatorAssertionResponse,
    AuthenticatorData,
    CollectedClientData,
)

from .models import (
    OperatorWebAuthnChallenge, OperatorWebAuthnCredential,
    OperatorWebAuthnRegistration, OperatorWebAuthnPossessionChallenge,
    OperatorWebAuthnEnrollmentApproval,
)
from .operator_webauthn_registry import (
    begin_registered_operator_challenge,
    complete_registered_operator_challenge,
    revoke_registered_operator_credential,
)


RP = "auth.jireh.example.invalid"
ORIGIN = "https://" + RP
CREDENTIAL_ID = b"synthetic-credential-for-registry-2026"
PASSWORD = "Synthetic-Registry-Only-Operator-Password-2026!"


class OperatorCredentialRegistryTests(TransactionTestCase):
    def setUp(self):
        User = get_user_model()
        self.operator = User.objects.create_superuser(
            username="registry-operator-one",
            email="registry-one@example.invalid",
            password=PASSWORD,
        )
        self.second = User.objects.create_superuser(
            username="registry-operator-two",
            email="registry-two@example.invalid",
            password=PASSWORD,
        )
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.enrollment = bytes(AttestedCredentialData.create(
            b"\x00" * 16, CREDENTIAL_ID,
            ES256.from_cryptography_key(self.key.public_key()),
        ))
        self.digest = hashlib.sha256(CREDENTIAL_ID).hexdigest()
        self.credential = OperatorWebAuthnCredential.objects.create(
            operator=self.operator,
            credential_id_digest=self.digest,
            credential_data=self.enrollment,
            rp_id=RP, origin=ORIGIN,
            enrollment_verified_at=None,
        )
        # Synthetic approval chain for this test fixture. PostgreSQL must
        # verify that even test credentials cannot skip activation evidence.
        now = timezone.now()
        registration = OperatorWebAuthnRegistration.objects.create(
            operator=self.operator, rp_id=RP, origin=ORIGIN,
            challenge="synthetic-registry-registration-challenge",
            expires_at=now + timedelta(minutes=5),
            closed_at=now,
            credential_id_digest=self.digest,
        )
        possession = OperatorWebAuthnPossessionChallenge.objects.create(
            operator=self.operator, credential=self.credential,
            challenge="synthetic-registry-possession-challenge",
            expires_at=now + timedelta(minutes=5),
            closed_at=now, verified_at=now, verified_sign_count=0,
        )
        OperatorWebAuthnEnrollmentApproval.objects.create(
            operator=self.operator, approver=self.second,
            approver_role=OperatorWebAuthnEnrollmentApproval.ROLE_OWNER,
            credential=self.credential, registration=registration,
            possession_proof=possession,
            identity_verification_reference="SYNTHETIC-REGISTRY-APPROVAL-2026",
            approved_at=now,
        )
        self.credential.enrollment_verified_at = now
        self.credential.save(update_fields=["enrollment_verified_at", "updated_at"])
        guard = self.settings(
            JIREH_OPERATOR_WEBAUTHN_CHALLENGES_ENABLED=True,
            JIREH_BOOTSTRAP_OPERATOR_IDS=(self.operator.pk, self.second.pk),
        )
        guard.enable()
        self.addCleanup(guard.disable)

    def begin(self, *, operator=None, digest=None):
        return begin_registered_operator_challenge(
            operator=self.operator if operator is None else operator,
            credential_id_digest=self.digest if digest is None else digest,
        )

    def assertion(self, options, *, count=1, key=None, origin=ORIGIN):
        client = CollectedClientData.create(
            CollectedClientData.TYPE.GET,
            options.public_key.challenge,
            origin,
        )
        data = AuthenticatorData.create(
            sha256(RP.encode()),
            AuthenticatorData.FLAG.UP | AuthenticatorData.FLAG.UV,
            count,
        )
        signature = (key or self.key).sign(
            bytes(data) + client.hash,
            ec.ECDSA(hashes.SHA256()),
        )
        return AuthenticationResponse(
            raw_id=CREDENTIAL_ID,
            response=AuthenticatorAssertionResponse(
                client_data=client,
                authenticator_data=data,
                signature=signature,
            ),
        )

    def complete(self, request_id, assertion, *, operator=None):
        return complete_registered_operator_challenge(
            operator=self.operator if operator is None else operator,
            challenge_id=request_id, response=assertion,
        )

    def test_success_advances_counter_and_consumes_challenge(self):
        self.assertFalse(connection.in_atomic_block)
        options, request_id = self.begin()
        self.assertEqual(self.complete(request_id, self.assertion(options)), 1)
        self.credential.refresh_from_db()
        self.assertEqual(self.credential.sign_count, 1)
        record = OperatorWebAuthnChallenge.objects.get(pk=request_id)
        self.assertEqual(record.closed_at, record.verified_at)
        with self.assertRaises(PermissionDenied):
            self.complete(request_id, self.assertion(options))
        self.assertEqual(self.credential.sign_count, 1)
        self.assertFalse(connection.in_atomic_block)

    def test_second_assertion_rejects_reused_and_regressed_counter(self):
        first, first_id = self.begin()
        self.complete(first_id, self.assertion(first, count=5))
        second, second_id = self.begin()
        with self.assertRaises(PermissionDenied):
            self.complete(second_id, self.assertion(second, count=5))
        self.credential.refresh_from_db()
        self.assertEqual(self.credential.sign_count, 5)
        row = OperatorWebAuthnChallenge.objects.get(pk=second_id)
        self.assertIsNotNone(row.closed_at)
        self.assertIsNone(row.verified_at)

    def test_invalid_signature_consumes_challenge_without_counter_mutation(self):
        options, request_id = self.begin()
        attacker = ec.generate_private_key(ec.SECP256R1())
        with self.assertRaises(PermissionDenied):
            self.complete(request_id, self.assertion(options, key=attacker))
        self.assertIsNotNone(
            OperatorWebAuthnChallenge.objects.get(pk=request_id).closed_at
        )
        self.credential.refresh_from_db()
        self.assertEqual(self.credential.sign_count, 0)
        with self.assertRaises(PermissionDenied):
            self.complete(request_id, self.assertion(options))

    def test_unverified_credential_never_issues_a_challenge(self):
        unverified_id = b"synthetic-pending-verification-key-id"
        unverified_data = bytes(AttestedCredentialData.create(
            b"\x00" * 16, unverified_id,
            ES256.from_cryptography_key(self.key.public_key()),
        ))
        unverified_digest = hashlib.sha256(unverified_id).hexdigest()
        OperatorWebAuthnCredential.objects.create(
            operator=self.operator,
            credential_id_digest=unverified_digest,
            credential_data=unverified_data,
            rp_id=RP, origin=ORIGIN,
            enrollment_verified_at=None,
        )
        with self.assertRaises(PermissionDenied):
            self.begin(digest=unverified_digest)
        self.assertFalse(OperatorWebAuthnChallenge.objects.exists())

    def test_verified_enrollment_cannot_be_erased(self):
        self.credential.enrollment_verified_at = None
        with self.assertRaises(ValidationError):
            self.credential.save()

    def test_revocation_blocks_new_and_pending_challenges(self):
        options, request_id = self.begin()
        revoke_registered_operator_credential(
            operator=self.operator, credential_id_digest=self.digest,
        )
        self.credential.refresh_from_db()
        self.assertIsNotNone(self.credential.revoked_at)
        with self.assertRaises(PermissionDenied):
            self.complete(request_id, self.assertion(options))
        self.assertIsNotNone(
            OperatorWebAuthnChallenge.objects.get(pk=request_id).closed_at
        )
        with self.assertRaises(PermissionDenied):
            self.begin()
        with self.assertRaises(ValidationError):
            self.credential.revoked_at = None
            self.credential.save()

    def test_operator_binding_and_disabled_gate(self):
        with self.assertRaises(PermissionDenied):
            self.begin(operator=self.second)
        with self.settings(JIREH_OPERATOR_WEBAUTHN_CHALLENGES_ENABLED=False):
            with self.assertRaises(PermissionDenied):
                self.begin()
        self.assertFalse(OperatorWebAuthnChallenge.objects.exists())

    def test_caller_outer_transaction_is_rejected(self):
        with transaction.atomic():
            with self.assertRaises(PermissionDenied):
                self.begin()
        self.assertFalse(OperatorWebAuthnChallenge.objects.exists())

    def test_credential_identity_and_public_key_are_immutable(self):
        original = self.credential.credential_data
        self.credential.credential_id_digest = "a" * 64
        with self.assertRaises(ValidationError):
            self.credential.save()
        self.credential.refresh_from_db()
        self.credential.credential_data = bytes(original)[:-1] + bytes([original[-1] ^ 1])
        with self.assertRaises(ValidationError):
            self.credential.save()

    def test_postgresql_raw_counter_rollback_and_unrevocation_blocked(self):
        if connection.vendor != "postgresql":
            return
        first, challenge_id = self.begin()
        self.complete(challenge_id, self.assertion(first, count=7))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OperatorWebAuthnCredential.objects.filter(pk=self.credential.pk).update(
                    sign_count=6,
                )
        revoke_registered_operator_credential(
            operator=self.operator, credential_id_digest=self.digest,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OperatorWebAuthnCredential.objects.filter(pk=self.credential.pk).update(
                    revoked_at=None,
                )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OperatorWebAuthnCredential.objects.filter(pk=self.credential.pk).delete()

    def test_postgresql_unapproved_credential_activation_rejected(self):
        if connection.vendor != "postgresql":
            return
        pending_id = b"synthetic-unapproved-credential-key-2026"
        pending_key = ec.generate_private_key(ec.SECP256R1())
        pending_data = bytes(AttestedCredentialData.create(
            b"\x00" * 16, pending_id,
            ES256.from_cryptography_key(pending_key.public_key()),
        ))
        pending_digest = hashlib.sha256(pending_id).hexdigest()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OperatorWebAuthnCredential.objects.create(
                    operator=self.operator,
                    credential_id_digest=pending_digest,
                    credential_data=pending_data,
                    rp_id=RP, origin=ORIGIN,
                    enrollment_verified_at=timezone.now(),
                )
        pending = OperatorWebAuthnCredential.objects.create(
            operator=self.operator,
            credential_id_digest=pending_digest,
            credential_data=pending_data,
            rp_id=RP, origin=ORIGIN,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OperatorWebAuthnCredential.objects.filter(pk=pending.pk).update(
                    enrollment_verified_at=timezone.now(),
                )
        pending.refresh_from_db()
        self.assertIsNone(pending.enrollment_verified_at)
        self.assertFalse(
            OperatorWebAuthnEnrollmentApproval.objects.filter(
                credential=pending,
            ).exists()
        )

    def test_failed_database_update_rolls_back_challenge_success(self):
        options, request_id = self.begin()
        with patch(
            "jireh.schools.operator_webauthn_registry.OperatorWebAuthnCredential.save",
            side_effect=IntegrityError("synthetic registry storage failure"),
        ):
            with self.assertRaises(PermissionDenied):
                self.complete(request_id, self.assertion(options))
        self.credential.refresh_from_db()
        self.assertEqual(self.credential.sign_count, 0)
        self.assertIsNone(
            OperatorWebAuthnChallenge.objects.get(pk=request_id).verified_at
        )
