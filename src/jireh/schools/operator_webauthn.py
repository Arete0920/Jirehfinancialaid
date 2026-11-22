"""Internal-only WebAuthn assertion verification; NOT an operator login service.

The caller must own and durably consume the one-time challenge, bind it to an
authenticated operator and enrolled credential, and atomically persist the new
signature counter. This module does none of those operations and MUST NOT be
used as a privilege grant, session, MFA certificate, or production endpoint.

No CROWN or cloud dependency. Browser enrollment and operator attestation are
not enabled here. FIDO2 signature/RP/challenge verification is delegated to
Yubico python-fido2, never implemented by hand.
"""

import re

from fido2.server import Fido2Server
from fido2.webauthn import (
    AttestedCredentialData,
    AuthenticationResponse,
    UserVerificationRequirement,
)


_RP_ID = re.compile(
    r"\A(?=.{1,253}\Z)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+\Z"
)
_UV = UserVerificationRequirement.REQUIRED


def _server(*, rp_id, origin):
    """Only the exact HTTPS RP hostname is acceptable (no scheme/port aliases)."""
    if not isinstance(rp_id, str) or not _RP_ID.fullmatch(rp_id):
        raise ValueError("An exact lower-case WebAuthn RP hostname is required.")
    if not isinstance(origin, str) or origin != f"https://{rp_id}":
        raise ValueError("WebAuthn origin must be the exact HTTPS RP origin.")
    return Fido2Server(
        {"id": rp_id, "name": "Jireh Internal Operators"},
        verify_origin=lambda reported: reported == origin,
    )


def _known_credential(credential_data):
    """Accept only attested credential bytes from a trusted enrollment store."""
    if (not isinstance(credential_data, bytes)
            or not 64 <= len(credential_data) <= 4096):
        raise ValueError("A bounded, trusted enrolled credential is required.")
    try:
        credential = AttestedCredentialData(credential_data)
    except (ValueError, TypeError, AttributeError, IndexError, KeyError, OverflowError):
        # Invalid CBOR/COSE credentials must produce a bounded rejection rather
        # than exposing a decoder's internal exception to privileged callers.
        raise ValueError("Invalid enrolled credential data.") from None
    if not credential.credential_id:
        raise ValueError("The enrolled credential ID is missing.")
    return credential


def begin_operator_assertion(*, rp_id, origin, credential_data):
    """Generate a fresh challenge for exactly one previously enrolled key.

    The returned state is SENSITIVE SERVER-SIDE data. It is not a browser
    authorization token; a future store must bind, expire and consume it once.
    """
    server = _server(rp_id=rp_id, origin=origin)
    credential = _known_credential(credential_data)
    return server.authenticate_begin(
        [credential],
        user_verification=_UV,
    )


def verify_operator_assertion(
    *, rp_id, origin, credential_data, state, response, previous_sign_count
):
    """Cryptographically verify one assertion and return its increased count.

    Requiring a positive, strictly increasing signature counter deliberately
    excludes authenticators reporting a zero counter in this prototype.
    Durable, atomic challenge consumption and counter persistence have not
    been implemented; absent those controls, replay resistance is NOT certified.
    """
    server = _server(rp_id=rp_id, origin=origin)
    credential = _known_credential(credential_data)
    if (not isinstance(state, dict)
            or state.get("user_verification") != _UV
            or not isinstance(state.get("challenge"), str)
            or len(state["challenge"]) < 43):
        raise ValueError("Trusted, user-verified challenge state is required.")
    if (type(previous_sign_count) is not int
            or not 0 <= previous_sign_count <= 0xFFFFFFFF):
        raise ValueError("A valid stored authenticator counter is required.")

    assertion = AuthenticationResponse.from_dict(response)
    if assertion.response.client_data.cross_origin:
        raise ValueError("Cross-origin WebAuthn assertions are forbidden.")
    server.authenticate_complete(state, [credential], assertion)
    new_count = assertion.response.authenticator_data.counter
    if new_count <= previous_sign_count:
        raise ValueError("WebAuthn signature counter did not advance.")
    return new_count
