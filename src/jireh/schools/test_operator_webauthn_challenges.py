"""Synthetic transaction tests for durable internal WebAuthn challenges."""

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

from .models import OperatorWebAuthnChallenge
from .operator_webauthn_challenges import (
    begin_durable_operator_challenge,
    complete_durable_operator_challenge,
)


RP = "auth.jireh.example.invalid"
ORIGIN = "https://" + RP
CREDENTIAL_ID = b"jireh-synthetic-operator-credential"
PASSWORD = "Synthetic-Operator-Challenge-Password-2026!"


class DurableOperatorChallengeTests(TransactionTestCase):
    def setUp(self):
        User = get_user_model()
        self.operator = User.objects.create_superuser(
            username="challenge-operator-1",
            email="operator1@example.invalid",
            password=PASSWORD,
        )
        self.other = User.objects.create_superuser(
            username="challenge-operator-2",
            email="operator2@example.invalid",
            password=PASSWORD,
        )
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.enrollment = bytes(AttestedCredentialData.create(
            b"\x00" * 16,
            CREDENTIAL_ID,
            ES256.from_cryptography_key(self.key.public_key()),
        ))
        guard = self.settings(
            JIREH_OPERATOR_WEBAUTHN_CHALLENGES_ENABLED=True,
            JIREH_BOOTSTRAP_OPERATOR_IDS=(self.operator.pk, self.other.pk),
        )
        guard.enable()
        self.addCleanup(guard.disable)

    def begin(self, *, operator=None):
        return begin_durable_operator_challenge(
            operator=self.operator if operator is None else operator,
            rp_id=RP, origin=ORIGIN, credential_data=self.enrollment,
        )

    def assertion(self, options, *, counter=1, sign_key=None, origin=ORIGIN):
        client_data = CollectedClientData.create(
            CollectedClientData.TYPE.GET,
            options.public_key.challenge,
            origin,
        )
        auth_data = AuthenticatorData.create(
            sha256(RP.encode()),
            AuthenticatorData.FLAG.UP | AuthenticatorData.FLAG.UV,
            counter,
        )
        signature = (sign_key or self.key).sign(
            bytes(auth_data) + client_data.hash, ec.ECDSA(hashes.SHA256()),
        )
        return AuthenticationResponse(
            raw_id=CREDENTIAL_ID,
            response=AuthenticatorAssertionResponse(
                client_data=client_data,
                authenticator_data=auth_data,
                signature=signature,
            ),
        )

    def finish(self, challenge_id, assertion, *, operator=None, previous=0):
        return complete_durable_operator_challenge(
            operator=self.operator if operator is None else operator,
            challenge_id=challenge_id, rp_id=RP, origin=ORIGIN,
            credential_data=self.enrollment, response=assertion,
            previous_sign_count=previous,
        )

    def test_success_is_committed_and_replay_is_rejected(self):
        self.assertFalse(connection.in_atomic_block)
        options, challenge_id = self.begin()
        self.assertEqual(self.finish(challenge_id, self.assertion(options)), 1)
        record = OperatorWebAuthnChallenge.objects.get(pk=challenge_id)
        self.assertIsNotNone(record.closed_at)
        self.assertEqual(record.verified_at, record.closed_at)
        with self.assertRaises(PermissionDenied):
            self.finish(challenge_id, self.assertion(options))
        self.assertFalse(connection.in_atomic_block)

    def test_failed_signature_consumes_challenge(self):
        options, challenge_id = self.begin()
        attacker = ec.generate_private_key(ec.SECP256R1())
        with self.assertRaises(PermissionDenied):
            self.finish(
                challenge_id, self.assertion(options, sign_key=attacker),
            )
        record = OperatorWebAuthnChallenge.objects.get(pk=challenge_id)
        self.assertIsNotNone(record.closed_at)
        self.assertIsNone(record.verified_at)
        with self.assertRaises(PermissionDenied):
            self.finish(challenge_id, self.assertion(options))

    def test_expiry_is_closed_and_a_new_challenge_can_be_issued(self):
        options, challenge_id = self.begin()
        current = timezone.now()
        with patch(
            "jireh.schools.operator_webauthn_challenges.timezone.now",
            return_value=current + timedelta(minutes=6),
        ):
            with self.assertRaises(PermissionDenied):
                self.finish(challenge_id, self.assertion(options))
            _, next_id = self.begin()
        self.assertNotEqual(next_id, challenge_id)
        self.assertIsNotNone(
            OperatorWebAuthnChallenge.objects.get(pk=challenge_id).closed_at
        )
        self.assertIsNone(
            OperatorWebAuthnChallenge.objects.get(pk=next_id).closed_at
        )

    def test_pending_challenge_cannot_be_replaced_before_expiry(self):
        self.begin()
        with self.assertRaises(PermissionDenied):
            self.begin()
        self.assertEqual(OperatorWebAuthnChallenge.objects.count(), 1)

    def test_different_operator_cannot_consume_another_operators_challenge(self):
        options, challenge_id = self.begin()
        with self.assertRaises(PermissionDenied):
            self.finish(challenge_id, self.assertion(options), operator=self.other)
        self.assertIsNone(
            OperatorWebAuthnChallenge.objects.get(pk=challenge_id).closed_at
        )
        self.assertEqual(self.finish(challenge_id, self.assertion(options)), 1)

    def test_disabled_setting_and_outer_transactions_fail_closed(self):
        with self.settings(JIREH_OPERATOR_WEBAUTHN_CHALLENGES_ENABLED=False):
            with self.assertRaises(PermissionDenied):
                self.begin()
        self.assertEqual(OperatorWebAuthnChallenge.objects.count(), 0)
        with transaction.atomic():
            with self.assertRaises(PermissionDenied):
                self.begin()
        self.assertFalse(OperatorWebAuthnChallenge.objects.exists())

    def test_counter_failure_consumes_challenge(self):
        options, challenge_id = self.begin()
        with self.assertRaises(PermissionDenied):
            self.finish(challenge_id, self.assertion(options, counter=1), previous=1)
        row = OperatorWebAuthnChallenge.objects.get(pk=challenge_id)
        self.assertIsNotNone(row.closed_at)
        self.assertIsNone(row.verified_at)

    def test_closed_row_cannot_be_reopened_or_deleted(self):
        options, challenge_id = self.begin()
        self.finish(challenge_id, self.assertion(options))
        row = OperatorWebAuthnChallenge.objects.get(pk=challenge_id)
        row.closed_at = None
        with self.assertRaises(ValidationError):
            row.save()
        with self.assertRaises(ValidationError):
            row.delete()
        if connection.vendor == "postgresql":
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    OperatorWebAuthnChallenge.objects.filter(
                        pk=challenge_id,
                    ).update(closed_at=None)
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    OperatorWebAuthnChallenge.objects.filter(
                        pk=challenge_id,
                    ).delete()
