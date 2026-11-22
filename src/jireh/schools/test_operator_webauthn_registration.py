"""Synthetic-only registration ceremony tests, no real operator enrollment."""

import hashlib
from datetime import timedelta
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import ec
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone
from fido2.cose import ES256
from fido2.utils import sha256
from fido2.webauthn import (
    AttestationObject,
    AttestedCredentialData,
    AuthenticatorAttestationResponse,
    AuthenticatorData,
    CollectedClientData,
    RegistrationResponse,
)

from .models import OperatorWebAuthnCredential, OperatorWebAuthnRegistration
from .operator_webauthn_registration import (
    begin_operator_registration, complete_operator_registration,
)


RP = "auth.jireh.example.invalid"
ORIGIN = "https://" + RP
CREDENTIAL_ID = b"synthetic-register-new-credential-2026"


class OperatorRegistrationTests(TransactionTestCase):
    def setUp(self):
        User = get_user_model()
        self.operator = User.objects.create_superuser(
            username="registration-operator-one",
            email="one@example.invalid",
            password="Synthetic-Registration-Password-2026!",
        )
        self.other = User.objects.create_superuser(
            username="registration-operator-two",
            email="two@example.invalid",
            password="Synthetic-Registration-Password-2026!",
        )
        self.key = ec.generate_private_key(ec.SECP256R1())
        guard = self.settings(
            JIREH_OPERATOR_WEBAUTHN_REGISTRATION_ENABLED=True,
            JIREH_OPERATOR_WEBAUTHN_CHALLENGES_ENABLED=True,
            JIREH_BOOTSTRAP_OPERATOR_IDS=(self.operator.pk, self.other.pk),
        )
        guard.enable()
        self.addCleanup(guard.disable)

    def begin(self, *, operator=None):
        return begin_operator_registration(
            operator=self.operator if operator is None else operator,
            rp_id=RP, origin=ORIGIN,
        )

    def response(
        self, options, *, origin=ORIGIN, verified=True,
        credential_id=CREDENTIAL_ID, rp_id=RP, challenge=None,
        cross_origin=False, fmt="none",
    ):
        client = CollectedClientData.create(
            CollectedClientData.TYPE.CREATE,
            options.public_key.challenge if challenge is None else challenge,
            origin, cross_origin=cross_origin,
        )
        credential = AttestedCredentialData.create(
            b"\x00" * 16, credential_id,
            ES256.from_cryptography_key(self.key.public_key()),
        )
        flags = AuthenticatorData.FLAG.UP | AuthenticatorData.FLAG.AT
        if verified:
            flags |= AuthenticatorData.FLAG.UV
        auth = AuthenticatorData.create(
            sha256(rp_id.encode()), flags, 0, credential_data=credential,
        )
        return RegistrationResponse(
            raw_id=credential_id,
            response=AuthenticatorAttestationResponse(
                client_data=client,
                attestation_object=AttestationObject.create(fmt, auth, {}),
            ),
        )

    def finish(self, ceremony, result, *, operator=None):
        return complete_operator_registration(
            operator=self.operator if operator is None else operator,
            registration_id=ceremony, response=result,
        )

    def test_valid_registration_creates_only_unverified_credential(self):
        self.assertFalse(connection.in_atomic_block)
        options, ceremony = self.begin()
        digest = self.finish(ceremony, self.response(options))
        self.assertEqual(digest, hashlib.sha256(CREDENTIAL_ID).hexdigest())
        credential = OperatorWebAuthnCredential.objects.get(
            credential_id_digest=digest,
        )
        self.assertEqual(credential.operator_id, self.operator.pk)
        self.assertIsNone(credential.enrollment_verified_at)
        self.assertIsNone(credential.revoked_at)
        record = OperatorWebAuthnRegistration.objects.get(pk=ceremony)
        self.assertIsNotNone(record.closed_at)
        self.assertEqual(record.credential_id_digest, digest)
        with self.assertRaises(PermissionDenied):
            self.finish(ceremony, self.response(options))
        self.assertFalse(connection.in_atomic_block)

    def test_wrong_challenge_origin_rp_uv_and_cross_origin_are_consumed(self):
        variants = [
            {"challenge": b"an-invalid-challenge-32-bytes-long"},
            {"origin": "https://attacker.example.invalid"},
            {"rp_id": "attacker.example.invalid"},
            {"verified": False},
            {"cross_origin": True},
            {"fmt": "packed"},
        ]
        for case in variants:
            with self.subTest(case=case):
                options, ceremony = self.begin()
                with self.assertRaises(PermissionDenied):
                    self.finish(ceremony, self.response(options, **case))
                row = OperatorWebAuthnRegistration.objects.get(pk=ceremony)
                self.assertIsNotNone(row.closed_at)
                self.assertIsNone(row.credential_id_digest)
                self.assertFalse(OperatorWebAuthnCredential.objects.exists())

    def test_duplicate_key_is_denied_and_consumed(self):
        options, ceremony = self.begin()
        self.finish(ceremony, self.response(options))
        again, second = self.begin()
        with self.assertRaises(PermissionDenied):
            self.finish(second, self.response(again))
        self.assertEqual(OperatorWebAuthnCredential.objects.count(), 1)
        self.assertIsNotNone(
            OperatorWebAuthnRegistration.objects.get(pk=second).closed_at
        )

    def test_expiry_and_same_operator_pending_guard(self):
        options, ceremony = self.begin()
        with self.assertRaises(PermissionDenied):
            self.begin()
        current = timezone.now()
        with patch(
            "jireh.schools.operator_webauthn_registration.timezone.now",
            return_value=current + timedelta(minutes=6),
        ):
            with self.assertRaises(PermissionDenied):
                self.finish(ceremony, self.response(options))
            _, replacement = self.begin()
        self.assertNotEqual(ceremony, replacement)
        self.assertIsNotNone(
            OperatorWebAuthnRegistration.objects.get(pk=ceremony).closed_at
        )
        self.assertFalse(OperatorWebAuthnCredential.objects.exists())

    def test_other_operator_cannot_complete(self):
        options, ceremony = self.begin()
        with self.assertRaises(PermissionDenied):
            self.finish(ceremony, self.response(options), operator=self.other)
        self.assertIsNone(
            OperatorWebAuthnRegistration.objects.get(pk=ceremony).closed_at
        )

    def test_disabled_and_caller_owned_transactions_denied(self):
        with self.settings(JIREH_OPERATOR_WEBAUTHN_REGISTRATION_ENABLED=False):
            with self.assertRaises(PermissionDenied):
                self.begin()
        with transaction.atomic():
            with self.assertRaises(PermissionDenied):
                self.begin()
        self.assertFalse(OperatorWebAuthnRegistration.objects.exists())

    def test_immutable_ceremony_and_postgres_raw_reopen_fail(self):
        options, ceremony = self.begin()
        self.finish(ceremony, self.response(options))
        row = OperatorWebAuthnRegistration.objects.get(pk=ceremony)
        row.closed_at = None
        with self.assertRaises(ValidationError):
            row.save()
        with self.assertRaises(ValidationError):
            row.delete()
        if connection.vendor == "postgresql":
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    OperatorWebAuthnRegistration.objects.filter(
                        pk=ceremony,
                    ).update(closed_at=None)

    def test_storage_failure_cannot_leave_verification_or_active_credential(self):
        options, ceremony = self.begin()
        with patch(
            "jireh.schools.operator_webauthn_registration.OperatorWebAuthnCredential.objects.create",
            side_effect=IntegrityError("synthetic database failure"),
        ):
            with self.assertRaises(PermissionDenied):
                self.finish(ceremony, self.response(options))
        self.assertFalse(OperatorWebAuthnCredential.objects.exists())
        self.assertIsNone(
            OperatorWebAuthnRegistration.objects.get(pk=ceremony).closed_at
        )
