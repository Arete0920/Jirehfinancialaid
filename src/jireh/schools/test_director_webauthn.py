"""Actual signed assertions against disposable school director credentials."""
import hashlib
from datetime import timedelta
from unittest import skipUnless

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from fido2.cose import ES256
from fido2.utils import sha256
from fido2.webauthn import (
    AttestedCredentialData, AuthenticationResponse, AuthenticatorAssertionResponse,
    AuthenticatorData, CollectedClientData,
)

from .director_webauthn import begin_director_assertion, complete_director_assertion
from .models import DirectorWebAuthnChallenge, DirectorWebAuthnCredential, School, SchoolStaffAccess

RP = "director.jireh.example.invalid"
SESSION = "a" * 32
CREDENTIAL_ID = b"synthetic-school-director-credential"


@override_settings(JIREH_DIRECTOR_WEBAUTHN_ACCEPTANCE=True, JIREH_DIRECTOR_WEBAUTHN_RP_ID=RP)
class DirectorAssertionTests(TransactionTestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username="director")
        self.other = get_user_model().objects.create_user(username="other-director")
        self.admin = get_user_model().objects.create_superuser(username="arete-admin")
        self.school = School.objects.create(code="director-a", name="Fictional A")
        self.other_school = School.objects.create(code="director-b", name="Fictional B")
        self.grant = SchoolStaffAccess.objects.create(
            school=self.school, user=self.actor, role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        )
        SchoolStaffAccess.objects.create(school=self.other_school, user=self.other,
                                         role=SchoolStaffAccess.ROLE_AID_DIRECTOR)
        SchoolStaffAccess.objects.create(school=self.school, user=self.admin,
                                         role=SchoolStaffAccess.ROLE_AID_DIRECTOR)
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.digest = hashlib.sha256(CREDENTIAL_ID).hexdigest()
        self.credential = DirectorWebAuthnCredential.objects.create(
            grant=self.grant, credential_id_digest=self.digest,
            credential_data=bytes(AttestedCredentialData.create(
                bytes(16), CREDENTIAL_ID, ES256.from_cryptography_key(self.key.public_key()),
            )), rp_id=RP, enrollment_verified_at=timezone.now(),
        )

    def begin(self, **overrides):
        return begin_director_assertion(**{
            "actor": self.actor, "school_id": self.school.pk, "session_key": SESSION,
            "credential_id_digest": self.digest, **overrides,
        })

    def assertion(self, options, *, count=1, key=None, origin="https://" + RP, uv=True):
        client = CollectedClientData.create(CollectedClientData.TYPE.GET, options.public_key.challenge, origin)
        flags = AuthenticatorData.FLAG.UP | (AuthenticatorData.FLAG.UV if uv else 0)
        data = AuthenticatorData.create(sha256(RP.encode()), flags, count)
        signature = (key or self.key).sign(bytes(data) + client.hash, ec.ECDSA(hashes.SHA256()))
        return AuthenticationResponse(raw_id=CREDENTIAL_ID, response=AuthenticatorAssertionResponse(
            client_data=client, authenticator_data=data, signature=signature,
        ))

    def complete(self, row, response, **overrides):
        return complete_director_assertion(**{
            "actor": self.actor, "school_id": self.school.pk, "session_key": SESSION,
            "challenge_id": row, "response": response, **overrides,
        })

    def assert_counter(self, count):
        self.credential.refresh_from_db()
        self.assertEqual(self.credential.sign_count, count)

    def test_signed_assertion_advances_counter_and_replay_is_denied(self):
        options, row = self.begin()
        self.assertEqual(self.complete(row, self.assertion(options)), row)
        self.assert_counter(1)
        proof = DirectorWebAuthnChallenge.objects.get(pk=row)
        self.assertEqual(proof.verified_at, proof.closed_at)
        self.assertEqual(proof.verified_sign_count, 1)
        self.assertNotEqual(proof.session_digest, SESSION)
        with self.assertRaises(PermissionDenied):
            self.complete(row, self.assertion(options, count=2))
        self.assert_counter(1)
        options, row = self.begin()
        with self.assertRaises(PermissionDenied):
            self.complete(row, self.assertion(options, count=1))
        self.assert_counter(1)

    def test_wrong_session_actor_school_cannot_consume_proof(self):
        options, row = self.begin()
        for values in ({"actor": self.other}, {"actor": self.admin},
                       {"school_id": self.other_school.pk}, {"session_key": "b" * 32}):
            with self.subTest(values=values), self.assertRaises(PermissionDenied):
                self.complete(row, self.assertion(options), **values)
            self.assertIsNone(DirectorWebAuthnChallenge.objects.get(pk=row).closed_at)
        self.assertEqual(self.complete(row, self.assertion(options)), row)

    def test_wrong_signature_origin_and_missing_uv_consume_proof(self):
        for overrides in ({"key": ec.generate_private_key(ec.SECP256R1())},
                          {"origin": "https://other.example.invalid"}, {"uv": False}):
            options, row = self.begin()
            with self.subTest(overrides=overrides), self.assertRaises(PermissionDenied):
                self.complete(row, self.assertion(options, **overrides))
            proof = DirectorWebAuthnChallenge.objects.get(pk=row)
            self.assertIsNotNone(proof.closed_at)
            self.assertIsNone(proof.verified_at)
            self.assert_counter(0)

    def test_revocation_and_inactive_grant_deny(self):
        options, row = self.begin()
        self.credential.revoked_at = timezone.now()
        self.credential.save(update_fields=["revoked_at", "updated_at"])
        with self.assertRaises(PermissionDenied):
            self.complete(row, self.assertion(options))
        with self.assertRaises(PermissionDenied):
            self.begin()
        self.assert_counter(0)
        self.grant.is_active = False
        self.grant.save(update_fields=["is_active", "updated_at"])
        with self.assertRaises(PermissionDenied):
            self.begin()

    def test_disabled_gate_wrong_rp_and_pending_challenge(self):
        for settings in ({"JIREH_DIRECTOR_WEBAUTHN_ACCEPTANCE": False},
                         {"JIREH_DIRECTOR_WEBAUTHN_RP_ID": "other.example.invalid"},
                         {"SETTINGS_MODULE": "jireh.runtime.settings"}):
            with self.settings(**settings), self.assertRaises(PermissionDenied):
                self.begin()
        self.assertFalse(DirectorWebAuthnChallenge.objects.exists())
        self.begin()
        with self.assertRaises(PermissionDenied):
            self.begin()

    def test_nullable_verification_cannot_bypass_database_constraint(self):
        _, row = self.begin()
        now = timezone.now()
        for fields in ({"verified_at": now, "closed_at": now},
                       {"verified_at": now, "verified_sign_count": 1}):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                DirectorWebAuthnChallenge.objects.filter(pk=row).update(**fields)

    def test_orm_credential_binding_and_challenge_history_immutable(self):
        self.credential.rp_id = "other.example.invalid"
        with self.assertRaises(ValidationError):
            self.credential.save()
        options, row = self.begin()
        self.complete(row, self.assertion(options))
        proof = DirectorWebAuthnChallenge.objects.get(pk=row)
        proof.closed_at = None
        with self.assertRaises(ValidationError):
            proof.save()

    @skipUnless(connection.vendor == "postgresql", "PostgreSQL trigger evidence required")
    def test_direct_database_rewrites_and_inconsistent_proofs_are_rejected(self):
        options, row = self.begin()
        records = DirectorWebAuthnChallenge.objects.filter(pk=row)
        credentials = DirectorWebAuthnCredential.objects.filter(pk=self.credential.pk)
        now = timezone.now()
        for operation in (
            lambda: records.update(session_digest="b" * 64),
            lambda: credentials.update(rp_id="other.example.invalid"),
            lambda: records.update(verified_at=now, closed_at=now, verified_sign_count=1),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()
        self.complete(row, self.assertion(options))
        for operation in (
            lambda: credentials.update(sign_count=0),
            lambda: records.update(verified_at=None, closed_at=None, verified_sign_count=None),
            lambda: records.delete(),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()
        self.assert_counter(1)
