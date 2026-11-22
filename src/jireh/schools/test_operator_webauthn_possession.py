"""Synthetic pending WebAuthn key possession tests; no real operator enrollment.

Expected failure before implementation: the pending proof service/model do not
exist. Production activation and enrollment identity approval stay disabled.
"""

import hashlib
from datetime import timedelta
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone
from fido2.cose import ES256
from fido2.utils import sha256
from fido2.webauthn import (
    AttestationObject,
    AttestedCredentialData,
    AuthenticationResponse,
    AuthenticatorAssertionResponse,
    AuthenticatorAttestationResponse,
    AuthenticatorData,
    CollectedClientData,
    RegistrationResponse,
)

from .models import OperatorWebAuthnCredential
from .operator_webauthn_registration import (
    begin_operator_registration,
    complete_operator_registration,
)
from .operator_webauthn_registry import begin_registered_operator_challenge

RP = "auth.jireh.example.invalid"
ORIGIN = "https://" + RP
CREDENTIAL_ID = b"synthetic-pending-possession-key-2026"


class PendingWebAuthnPossessionTests(TransactionTestCase):
    def setUp(self):
        User = get_user_model()
        self.operator = User.objects.create_superuser(
            username="possession-operator",
            email="possession@example.invalid",
            password="Synthetic-Only-Possession-Operator-2026!",
        )
        self.other = User.objects.create_superuser(
            username="other-possession-operator",
            email="other-possession@example.invalid",
            password="Synthetic-Only-Possession-Operator-2026!",
        )
        guard = self.settings(
            JIREH_OPERATOR_WEBAUTHN_REGISTRATION_ENABLED=True,
            JIREH_OPERATOR_WEBAUTHN_CHALLENGES_ENABLED=True,
            JIREH_OPERATOR_WEBAUTHN_POSSESSION_ENABLED=True,
            JIREH_BOOTSTRAP_OPERATOR_IDS=(self.operator.pk, self.other.pk),
        )
        guard.enable()
        self.addCleanup(guard.disable)
        self.key = ec.generate_private_key(ec.SECP256R1())
        registration_options, registration_id = begin_operator_registration(
            operator=self.operator, rp_id=RP, origin=ORIGIN,
        )
        client = CollectedClientData.create(
            CollectedClientData.TYPE.CREATE,
            registration_options.public_key.challenge,
            ORIGIN,
        )
        attested_key = AttestedCredentialData.create(
            b"\x00" * 16, CREDENTIAL_ID,
            ES256.from_cryptography_key(self.key.public_key()),
        )
        authenticator_data = AuthenticatorData.create(
            sha256(RP.encode()),
            AuthenticatorData.FLAG.UP | AuthenticatorData.FLAG.AT
            | AuthenticatorData.FLAG.UV,
            0,
            credential_data=attested_key,
        )
        registration_response = RegistrationResponse(
            raw_id=CREDENTIAL_ID,
            response=AuthenticatorAttestationResponse(
                client_data=client,
                attestation_object=AttestationObject.create(
                    "none", authenticator_data, {},
                ),
            ),
        )
        self.digest = complete_operator_registration(
            operator=self.operator, registration_id=registration_id,
            response=registration_response,
        )

    def proof_api(self):
        # Import only at runtime so the RED test produces an ordinary assertion
        # before the implementation exists, not a test collection error.
        try:
            from . import operator_webauthn_possession
            from .models import OperatorWebAuthnPossessionChallenge
        except (ImportError, AttributeError):
            self.fail("Pending WebAuthn possession API not implemented")
        return operator_webauthn_possession, OperatorWebAuthnPossessionChallenge

    def begin(self, *, operator=None, digest=None):
        api, _ = self.proof_api()
        return api.begin_pending_key_proof(
            operator=operator or self.operator,
            credential_id_digest=self.digest if digest is None else digest,
        )

    def complete(self, proof_id, response, *, operator=None):
        api, _ = self.proof_api()
        return api.complete_pending_key_proof(
            operator=operator or self.operator,
            proof_id=proof_id,
            response=response,
        )

    def assertion(self, options, *, signing_key=None, count=1, origin=ORIGIN):
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
        sig = (signing_key or self.key).sign(
            bytes(data) + client.hash, ec.ECDSA(hashes.SHA256()),
        )
        return AuthenticationResponse(
            raw_id=CREDENTIAL_ID,
            response=AuthenticatorAssertionResponse(
                client_data=client,
                authenticator_data=data,
                signature=sig,
            ),
        )

    def test_proof_records_once_and_never_activates_enrollment(self):
        api, Evidence = self.proof_api()
        self.assertFalse(connection.in_atomic_block)
        options, proof_id = self.begin()
        self.assertEqual(
            self.complete(proof_id, self.assertion(options)),
            self.digest,
        )
        row = Evidence.objects.get(pk=proof_id)
        self.assertIsNotNone(row.verified_at)
        self.assertEqual(row.verified_at, row.closed_at)
        credential = OperatorWebAuthnCredential.objects.get(
            credential_id_digest=self.digest,
        )
        self.assertEqual(credential.sign_count, 1)
        self.assertIsNone(credential.enrollment_verified_at)
        with self.assertRaises(PermissionDenied):
            begin_registered_operator_challenge(
                operator=self.operator, credential_id_digest=self.digest,
            )
        with self.assertRaises(PermissionDenied):
            self.complete(proof_id, self.assertion(options))
        self.assertFalse(connection.in_atomic_block)

    def test_invalid_signature_consumes_proof_without_counter_change(self):
        _, Evidence = self.proof_api()
        options, proof_id = self.begin()
        attacker = ec.generate_private_key(ec.SECP256R1())
        with self.assertRaises(PermissionDenied):
            self.complete(
                proof_id, self.assertion(options, signing_key=attacker),
            )
        row = Evidence.objects.get(pk=proof_id)
        self.assertIsNotNone(row.closed_at)
        self.assertIsNone(row.verified_at)
        self.assertEqual(
            OperatorWebAuthnCredential.objects.get(
                credential_id_digest=self.digest,
            ).sign_count, 0,
        )

    def test_operator_isolation_and_open_proof_singleton(self):
        options, proof_id = self.begin()
        with self.assertRaises(PermissionDenied):
            self.begin()
        with self.assertRaises(PermissionDenied):
            self.complete(proof_id, self.assertion(options), operator=self.other)
        self.assertEqual(
            self.complete(proof_id, self.assertion(options)),
            self.digest,
        )

    def test_expired_proof_is_closed_and_can_be_reissued(self):
        api, Evidence = self.proof_api()
        options, proof_id = self.begin()
        now = timezone.now()
        with patch(
            "jireh.schools.operator_webauthn_possession.timezone.now",
            return_value=now + timedelta(minutes=6),
        ):
            with self.assertRaises(PermissionDenied):
                self.complete(proof_id, self.assertion(options))
            _, next_id = self.begin()
        self.assertNotEqual(proof_id, next_id)
        self.assertIsNotNone(Evidence.objects.get(pk=proof_id).closed_at)

    def test_reused_or_zero_signature_count_does_not_prove_possession(self):
        _, Evidence = self.proof_api()
        options, proof_id = self.begin()
        with self.assertRaises(PermissionDenied):
            self.complete(proof_id, self.assertion(options, count=0))
        self.assertIsNone(Evidence.objects.get(pk=proof_id).verified_at)
        credential = OperatorWebAuthnCredential.objects.get(
            credential_id_digest=self.digest,
        )
        self.assertEqual(credential.sign_count, 0)

    def test_revoked_pending_key_cannot_prove_possession(self):
        options, proof_id = self.begin()
        OperatorWebAuthnCredential.objects.filter(
            credential_id_digest=self.digest,
        ).update(revoked_at=timezone.now())
        with self.assertRaises(PermissionDenied):
            self.complete(proof_id, self.assertion(options))
        with self.assertRaises(PermissionDenied):
            self.begin()

    def test_feature_default_off_and_outer_transactions_rejected(self):
        with self.settings(JIREH_OPERATOR_WEBAUTHN_POSSESSION_ENABLED=False):
            with self.assertRaises(PermissionDenied):
                self.begin()
        with transaction.atomic():
            with self.assertRaises(PermissionDenied):
                self.begin()
        self.assertFalse(connection.in_atomic_block)

    def test_postgres_proof_history_cannot_reopen_or_delete(self):
        _, Evidence = self.proof_api()
        options, proof_id = self.begin()
        self.complete(proof_id, self.assertion(options))
        if connection.vendor != "postgresql":
            return
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Evidence.objects.filter(pk=proof_id).update(closed_at=None)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Evidence.objects.filter(pk=proof_id).delete()

    def test_failed_counter_write_rolls_back_success(self):
        _, Evidence = self.proof_api()
        options, proof_id = self.begin()
        with patch(
            "jireh.schools.operator_webauthn_possession.OperatorWebAuthnCredential.save",
            side_effect=IntegrityError("synthetic database outage"),
        ):
            with self.assertRaises(PermissionDenied):
                self.complete(proof_id, self.assertion(options))
        self.assertIsNone(Evidence.objects.get(pk=proof_id).closed_at)
        self.assertEqual(
            OperatorWebAuthnCredential.objects.get(
                credential_id_digest=self.digest,
            ).sign_count, 0,
        )
