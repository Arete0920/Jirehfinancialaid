"""Disabled internal proof of possession for UNVERIFIED operator credentials.

A cryptographic assertion updates a pending credential's counter and records
irreversible evidence. It NEVER authorizes an operator, marks identity approved,
activates a key, issues an MFA verdict, or creates an HTTP endpoint.
"""

import re
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, transaction
from django.utils import timezone

from .models import OperatorWebAuthnCredential, OperatorWebAuthnPossessionChallenge
from .operator_webauthn import begin_operator_assertion, verify_operator_assertion
from .operator_webauthn_challenges import _operator_locked


_LIFETIME = timedelta(minutes=5)
_DIGEST = re.compile(r"\A[0-9a-f]{64}\Z")


def _guard():
    if getattr(settings, "JIREH_OPERATOR_WEBAUTHN_POSSESSION_ENABLED", False) is not True:
        raise PermissionDenied("Operator possession verification is disabled.")


def _pending_credential(*, account, digest):
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise PermissionDenied("Pending operator credential required.")
    record = (
        OperatorWebAuthnCredential.objects.select_for_update()
        .filter(
            operator=account, credential_id_digest=digest,
            enrollment_verified_at__isnull=True, revoked_at__isnull=True,
        )
        .first()
    )
    if record is None:
        raise PermissionDenied("Pending operator credential required.")
    return record


def begin_pending_key_proof(*, operator, credential_id_digest):
    """Create a single short-lived challenge for the already registered key."""
    _guard()
    try:
        with transaction.atomic(durable=True):
            account = _operator_locked(operator)
            credential = _pending_credential(
                account=account, digest=credential_id_digest,
            )
            options, state = begin_operator_assertion(
                rp_id=credential.rp_id, origin=credential.origin,
                credential_data=bytes(credential.credential_data),
            )
            now = timezone.now()
            old = (
                OperatorWebAuthnPossessionChallenge.objects.select_for_update()
                .filter(operator=account, closed_at__isnull=True)
                .first()
            )
            if old is not None:
                if now < old.expires_at:
                    raise PermissionDenied("Proof already pending.")
                old.closed_at = now
                old.save(update_fields=["closed_at", "updated_at"])
            proof = OperatorWebAuthnPossessionChallenge.objects.create(
                operator=account, credential=credential,
                challenge=state["challenge"], expires_at=now + _LIFETIME,
            )
            return options, proof.pk
    except (DatabaseError, RuntimeError):
        raise PermissionDenied("Possession evidence storage unavailable.") from None


def complete_pending_key_proof(*, operator, proof_id, response):
    """Consume one proof; persist the counter atomically with verification.

    On bad signatures or revoked/expired credentials, the evidence is closed
    without a valid proof. No authority is returned or activated.
    """
    _guard()
    try:
        with transaction.atomic(durable=True):
            account = _operator_locked(operator)
            proof = (
                OperatorWebAuthnPossessionChallenge.objects.select_for_update()
                .filter(pk=proof_id, operator=account).first()
            )
            if proof is None or proof.closed_at is not None:
                raise PermissionDenied("Pending proof unavailable.")

            now = timezone.now()
            proof.closed_at = now
            count = None
            credential = (
                OperatorWebAuthnCredential.objects.select_for_update()
                .filter(
                    pk=proof.credential_id, operator=account,
                    enrollment_verified_at__isnull=True,
                    revoked_at__isnull=True,
                ).first()
            )
            if credential is not None and now < proof.expires_at:
                try:
                    count = verify_operator_assertion(
                        rp_id=credential.rp_id,
                        origin=credential.origin,
                        credential_data=bytes(credential.credential_data),
                        state={
                            "challenge": proof.challenge,
                            "user_verification": "required",
                        },
                        response=response,
                        previous_sign_count=credential.sign_count,
                    )
                except (ValueError, TypeError, KeyError, AttributeError):
                    pass
            if count is not None:
                credential.sign_count = count
                credential.save(update_fields=["sign_count", "updated_at"])
                proof.verified_at = now
                proof.verified_sign_count = count
            proof.save(update_fields=[
                "closed_at", "verified_at",
                "verified_sign_count", "updated_at",
            ])
            digest = credential.credential_id_digest if count is not None else None
    except (DatabaseError, RuntimeError):
        raise PermissionDenied("Possession evidence storage unavailable.") from None
    if digest is None:
        raise PermissionDenied("Pending operator credential possession rejected.")
    return digest
