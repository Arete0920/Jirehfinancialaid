"""Internal-only registry-backed operator WebAuthn challenge verification.

NO enrollment, public endpoint, session, MFA approval or privilege grant.
Trusted verified enrollment records must exist already. Challenge consumption
and signature counter update share one durable transaction. A rejected
assertion consumes its challenge and cannot mutate a credential.
"""

import hashlib
import re

from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, transaction
from django.utils import timezone

from .models import OperatorWebAuthnChallenge, OperatorWebAuthnCredential
from .operator_webauthn import begin_operator_assertion, verify_operator_assertion
from .operator_webauthn_challenges import (
    CHALLENGE_LIFETIME,
    _operator_locked,
)

_DIGEST = re.compile(r"\A[0-9a-f]{64}\Z")


def _trusted_credential(*, operator, digest):
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise PermissionDenied("Verified operator credential required.")
    credential = (
        OperatorWebAuthnCredential.objects.select_for_update()
        .filter(
            operator=operator,
            credential_id_digest=digest,
            enrollment_verified_at__isnull=False,
            revoked_at__isnull=True,
        )
        .first()
    )
    if credential is None:
        raise PermissionDenied("Verified operator credential required.")
    return credential


def begin_registered_operator_challenge(
    *, operator, credential_id_digest
):
    """Issue a one-use challenge for a database-verified, active public key."""
    try:
        with transaction.atomic(durable=True):
            account = _operator_locked(operator)
            credential = _trusted_credential(
                operator=account, digest=credential_id_digest,
            )
            options, state = begin_operator_assertion(
                rp_id=credential.rp_id, origin=credential.origin,
                credential_data=bytes(credential.credential_data),
            )
            now = timezone.now()
            existing = (
                OperatorWebAuthnChallenge.objects.select_for_update()
                .filter(operator=account, closed_at__isnull=True)
                .first()
            )
            if existing is not None:
                if now < existing.expires_at:
                    raise PermissionDenied("Operator already has a pending challenge.")
                existing.closed_at = now
                existing.save(update_fields=["closed_at", "updated_at"])
            record = OperatorWebAuthnChallenge.objects.create(
                operator=account,
                rp_id=credential.rp_id,
                origin=credential.origin,
                credential_id_digest=credential.credential_id_digest,
                challenge=state["challenge"],
                expires_at=now + CHALLENGE_LIFETIME,
            )
            return options, record.pk
    except (DatabaseError, RuntimeError):
        raise PermissionDenied("Operator WebAuthn registry unavailable.") from None


def complete_registered_operator_challenge(
    *, operator, challenge_id, response
):
    """Consume challenge and atomically advance the trusted credential count.

    Returns a new signature counter ONLY, not an authenticated session,
    MFA certification or authority to perform privileged operations.
    """
    try:
        with transaction.atomic(durable=True):
            account = _operator_locked(operator)
            row = (
                OperatorWebAuthnChallenge.objects.select_for_update()
                .filter(pk=challenge_id, operator=account)
                .first()
            )
            if row is None or row.closed_at is not None:
                raise PermissionDenied("WebAuthn challenge unavailable.")

            now = timezone.now()
            row.closed_at = now
            verified_counter = None
            credential = (
                OperatorWebAuthnCredential.objects.select_for_update()
                .filter(
                    operator=account,
                    credential_id_digest=row.credential_id_digest,
                    enrollment_verified_at__isnull=False,
                    revoked_at__isnull=True,
                    rp_id=row.rp_id,
                    origin=row.origin,
                )
                .first()
            )
            if credential is not None and now < row.expires_at:
                try:
                    verified_counter = verify_operator_assertion(
                        rp_id=row.rp_id,
                        origin=row.origin,
                        credential_data=bytes(credential.credential_data),
                        state={
                            "challenge": row.challenge,
                            "user_verification": "required",
                        },
                        response=response,
                        previous_sign_count=credential.sign_count,
                    )
                except (ValueError, TypeError, KeyError, AttributeError):
                    pass

            if verified_counter is not None:
                credential.sign_count = verified_counter
                credential.save(update_fields=["sign_count", "updated_at"])
                row.verified_at = now
            row.save(update_fields=["closed_at", "verified_at", "updated_at"])
    except (DatabaseError, RuntimeError):
        raise PermissionDenied("Operator WebAuthn registry unavailable.") from None

    if verified_counter is None:
        raise PermissionDenied("Operator WebAuthn assertion rejected.")
    return verified_counter


def revoke_registered_operator_credential(*, operator, credential_id_digest):
    """Irreversibly revoke one credential; requires trusted operator context.

    This is not an HTTP self-service endpoint, enrollment or account recovery.
    An issued, pending challenge is not reopened after revocation.
    """
    try:
        with transaction.atomic(durable=True):
            account = _operator_locked(operator)
            credential = _trusted_credential(
                operator=account, digest=credential_id_digest,
            )
            credential.revoked_at = timezone.now()
            credential.save(update_fields=["revoked_at", "updated_at"])
    except (DatabaseError, RuntimeError):
        raise PermissionDenied("Operator WebAuthn registry unavailable.") from None
