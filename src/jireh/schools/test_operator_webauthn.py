"""Synthetic local cryptographic WebAuthn assertions: no real operators or keys."""

import unittest

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from fido2.cose import ES256
from fido2.utils import sha256
from fido2.webauthn import (
    AttestedCredentialData,
    AuthenticationResponse,
    AuthenticatorAssertionResponse,
    AuthenticatorData,
    CollectedClientData,
    UserVerificationRequirement,
)

from .operator_webauthn import begin_operator_assertion, verify_operator_assertion


RP = "auth.jireh.example.invalid"
ORIGIN = "https://" + RP
CREDENTIAL_ID = b"synthetic-web-authn-credential-id"


class OperatorWebAuthnContractTests(unittest.TestCase):
    def setUp(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.enrolled = bytes(AttestedCredentialData.create(
            b"\x00" * 16,
            CREDENTIAL_ID,
            ES256.from_cryptography_key(self.key.public_key()),
        ))
        self.options, self.state = begin_operator_assertion(
            rp_id=RP, origin=ORIGIN, credential_data=self.enrolled,
        )

    def response(
        self, *, challenge=None, origin=ORIGIN, counter=5,
        verified=True, cross_origin=False, credential_id=CREDENTIAL_ID,
        signing_key=None, rp_id=RP,
    ):
        data = CollectedClientData.create(
            CollectedClientData.TYPE.GET,
            self.options.public_key.challenge if challenge is None else challenge,
            origin,
            cross_origin=cross_origin,
        )
        flags = AuthenticatorData.FLAG.UP
        if verified:
            flags |= AuthenticatorData.FLAG.UV
        auth = AuthenticatorData.create(
            sha256(rp_id.encode()), flags, counter,
        )
        signature = (signing_key or self.key).sign(
            bytes(auth) + data.hash,
            ec.ECDSA(hashes.SHA256()),
        )
        return AuthenticationResponse(
            raw_id=credential_id,
            response=AuthenticatorAssertionResponse(
                client_data=data,
                authenticator_data=auth,
                signature=signature,
            ),
        )

    def check(self, response, *, state=None, previous=4):
        return verify_operator_assertion(
            rp_id=RP, origin=ORIGIN, credential_data=self.enrolled,
            state=self.state if state is None else state,
            response=response, previous_sign_count=previous,
        )

    def test_valid_signature_challenge_origin_uv_and_counter(self):
        self.assertEqual(self.options.public_key.rp_id, RP)
        self.assertEqual(
            self.options.public_key.user_verification,
            UserVerificationRequirement.REQUIRED,
        )
        self.assertEqual(self.check(self.response()), 5)

    def test_invalid_origin_challenge_rp_and_cross_origin_fail(self):
        for response in (
            self.response(origin="https://evil.example.invalid"),
            self.response(challenge=b"other-32-byte-cryptographic-value"),
            self.response(rp_id="evil.example.invalid"),
            self.response(cross_origin=True),
        ):
            with self.subTest(response=response.response.client_data.origin):
                with self.assertRaises(ValueError):
                    self.check(response)

    def test_wrong_credential_signature_or_user_verification_fail(self):
        attacker = ec.generate_private_key(ec.SECP256R1())
        for response in (
            self.response(credential_id=b"attacker"),
            self.response(signing_key=attacker),
            self.response(verified=False),
        ):
            with self.assertRaises(ValueError):
                self.check(response)

    def test_non_increasing_counter_and_bad_stored_count_fail(self):
        for previous in (5, 6):
            with self.assertRaises(ValueError):
                self.check(self.response(counter=5), previous=previous)
        for previous in (-1, True, "4", 2**32):
            with self.assertRaises(ValueError):
                self.check(self.response(), previous=previous)

    def test_invalid_relying_party_or_untrusted_state_fail_closed(self):
        for rp, origin in (
            ("localhost", "https://localhost"),
            (RP, "http://" + RP),
            (RP, ORIGIN + ":443"),
            (RP.upper(), ORIGIN),
            (RP, "https://other.example.invalid"),
        ):
            with self.subTest(rp=rp, origin=origin):
                with self.assertRaises(ValueError):
                    begin_operator_assertion(
                        rp_id=rp, origin=origin,
                        credential_data=self.enrolled,
                    )
        for state in (
            {},
            {"challenge": self.state["challenge"], "user_verification": "preferred"},
            {"challenge": "x", "user_verification": UserVerificationRequirement.REQUIRED},
        ):
            with self.assertRaises(ValueError):
                self.check(self.response(), state=state)

    def test_bad_enrollment_bytes_rejected(self):
        for data in (None, b"", b"\x00" * 64):
            with self.assertRaises((ValueError, TypeError)):
                begin_operator_assertion(
                    rp_id=RP, origin=ORIGIN, credential_data=data,
                )
