"""Disabled-by-default WebAuthn registration ceremony; pending credentials only.

Registration verifies a challenge and the authenticator's RP/origin/user
verification flags using Yubico's python-fido2. With attestation='none' this
does NOT prove a trusted hardware manufacturer, operator identity, or
possession of a private key to an independent registrar. New credentials
remain UNVERIFIED and cannot authenticate until separately approved.
"""

import hashlib
import hmac
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone
from fido2.webauthn import (
    AttestationConveyancePreference,
    RegistrationResponse,
    UserVerificationRequirement,
)

from .models import OperatorWebAuthnCredential, OperatorWebAuthnRegistration
from .operator_webauthn import _known_credential, _server
from .operator_webauthn_challenges import _operator_locked


REGISTRATION_LIFETIME = timedelta(minutes=5)


def _enrollment_guard():
    if getattr(settings, "JIREH_OPERATOR_WEBAUTHN_REGISTRATION_ENABLED", False) is not True:
        raise PermissionDenied("Operator WebAuthn enrollment is disabled.")


def _registration_server(*, rp_id, origin):
    server = _server(rp_id=rp_id, origin=origin)
    server.attestation = AttestationConveyancePreference.NONE
    return server


def begin_operator_registration(*, operator, rp_id, origin):
    """Begin a one-use ceremony for an independently authenticated operator."""
    _enrollment_guard()
    try:
        with transaction.atomic(durable=True):
            account = _operator_locked(operator)
            server = _registration_server(rp_id=rp_id, origin=origin)
            options, state = server.register_begin(
                user={
                    "id": str(account.pk).encode("utf-8"),
                    "name": "internal-operator-" + str(account.pk),
                    "displayName": "Jireh Internal Operator",
                },
                user_verification=UserVerificationRequirement.REQUIRED,
            )
            now = timezone.now()
            existing = (
                OperatorWebAuthnRegistration.objects.select_for_update()
                .filter(operator=account, closed_at__isnull=True)
                .first()
            )
            if existing:
                if now < existing.expires_at:
                    raise PermissionDenied("Registration already pending.")
                existing.closed_at = now
                existing.save(update_fields=["closed_at", "updated_at"])
            record = OperatorWebAuthnRegistration.objects.create(
                operator=account,
                rp_id=rp_id,
                origin=origin,
                challenge=state["challenge"],
                expires_at=now + REGISTRATION_LIFETIME,
            )
            return options, record.pk
    except (DatabaseError, RuntimeError):
        raise PermissionDenied("Operator registration storage unavailable.") from None


def complete_operator_registration(*, operator, registration_id, response):
    """Consume ceremony and, on success, store an UNVERIFIED public credential.

    Invalid, expired or repeated submissions do not create credentials. This
    does NOT grant any operator authority, activate MFA or approve enrollment.
    """
    _enrollment_guard()
    try:
        with transaction.atomic(durable=True):
            account = _operator_locked(operator)
            record = (
                OperatorWebAuthnRegistration.objects.select_for_update()
                .filter(operator=account, pk=registration_id)
                .first()
            )
            if record is None or record.closed_at is not None:
                raise PermissionDenied("Registration unavailable.")
            now = timezone.now()
            record.closed_at = now
            digest = None
            credential_data = None
            counter = 0
            if now < record.expires_at:
                try:
                    parsed = RegistrationResponse.from_dict(response)
                    server = _registration_server(
                        rp_id=record.rp_id, origin=record.origin,
                    )
                    if parsed.response.client_data.cross_origin:
                        raise ValueError("Cross-origin WebAuthn registration denied.")
                    attestation = parsed.response.attestation_object
                    if attestation.fmt != "none":
                        raise ValueError("Only no-attestation pending enrollment is supported.")
                    auth_data = server.register_complete(
                        {
                            "challenge": record.challenge,
                            "user_verification": UserVerificationRequirement.REQUIRED,
                        },
                        parsed,
                    )
                    if auth_data.credential_data is None:
                        raise ValueError("Missing attested credential data.")
                    credential = _known_credential(bytes(auth_data.credential_data))
                    if not hmac.compare_digest(
                        parsed.raw_id, credential.credential_id,
                    ):
                        raise ValueError("Credential ID mismatch.")
                    digest = hashlib.sha256(credential.credential_id).hexdigest()
                    credential_data = bytes(credential)
                    counter = auth_data.counter
                except (ValueError, TypeError, KeyError, AttributeError,
                        IndexError, OverflowError):
                    pass

            if digest is not None:
                if not OperatorWebAuthnCredential.objects.filter(
                    credential_id_digest=digest,
                ).exists():
                    OperatorWebAuthnCredential.objects.create(
                        operator=account,
                        credential_id_digest=digest,
                        credential_data=credential_data,
                        rp_id=record.rp_id,
                        origin=record.origin,
                        sign_count=counter,
                        enrollment_verified_at=None,
                    )
                    record.credential_id_digest = digest
                else:
                    digest = None
            record.save(update_fields=[
                "closed_at", "credential_id_digest", "updated_at",
            ])
    except (DatabaseError, RuntimeError):
        raise PermissionDenied("Operator registration storage unavailable.") from None
    if digest is None:
        raise PermissionDenied("Operator registration rejected.")
    return digest
