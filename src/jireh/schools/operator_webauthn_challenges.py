"""Disabled-by-default durable WebAuthn challenge lifecycle for trusted operators.

This is internal library code, NOT operator authentication or MFA activation.
A caller must independently authenticate the operator, provision an enrolled
credential through a separately certified process, and persist the returned
signature counter atomically in a future credential registry. No public route.
"""

import hashlib
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, transaction
from django.utils import timezone

from .models import OperatorWebAuthnChallenge
from .operator_webauthn import (
    _known_credential,
    begin_operator_assertion,
    verify_operator_assertion,
)


CHALLENGE_LIFETIME = timedelta(minutes=5)


def _operator_locked(operator):
    if getattr(settings, "JIREH_OPERATOR_WEBAUTHN_CHALLENGES_ENABLED", False) is not True:
        raise PermissionDenied("Internal WebAuthn challenges disabled.")
    allowlist = getattr(settings, "JIREH_BOOTSTRAP_OPERATOR_IDS", ())
    if (
        not isinstance(allowlist, (tuple, frozenset))
        or len(allowlist) < 2
        or len(set(allowlist)) != len(allowlist)
        or not getattr(operator, "is_authenticated", False)
        or getattr(operator, "pk", None) not in allowlist
    ):
        raise PermissionDenied("Eligible operator required.")
    account = (
        get_user_model()._default_manager.select_for_update()
        .filter(pk=operator.pk, is_active=True, is_staff=True, is_superuser=True)
        .first()
    )
    if account is None:
        raise PermissionDenied("Eligible operator required.")
    return account


def _credential_digest(credential_data):
    credential = _known_credential(credential_data)
    return hashlib.sha256(credential.credential_id).hexdigest()


def begin_durable_operator_challenge(*, operator, rp_id, origin, credential_data):
    """Return browser options and opaque challenge UUID (no session or privilege).

    One outstanding request per operator. An expired request is closed before
    replacement. A failure to commit does not issue usable challenge evidence.
    """
    try:
        with transaction.atomic(durable=True):
            account = _operator_locked(operator)
            options, state = begin_operator_assertion(
                rp_id=rp_id, origin=origin, credential_data=credential_data,
            )
            now = timezone.now()
            existing = (
                OperatorWebAuthnChallenge.objects.select_for_update()
                .filter(operator=account, closed_at__isnull=True).first()
            )
            if existing is not None:
                if now < existing.expires_at:
                    raise PermissionDenied("Operator already has a pending challenge.")
                existing.closed_at = now
                existing.save(update_fields=["closed_at", "updated_at"])
            record = OperatorWebAuthnChallenge.objects.create(
                operator=account, rp_id=rp_id, origin=origin,
                credential_id_digest=_credential_digest(credential_data),
                challenge=state["challenge"],
                expires_at=now + CHALLENGE_LIFETIME,
            )
            return options, record.pk
    except (DatabaseError, RuntimeError):
        raise PermissionDenied("WebAuthn challenge storage unavailable.") from None


def complete_durable_operator_challenge(
    *, operator, challenge_id, rp_id, origin, credential_data,
    response, previous_sign_count,
):
    """Close the one-use challenge regardless of signature verification result.

    Returns the verified counter, NOT an MFA/session/authorization result.
    Counter storage and enrollment are NOT implemented. A failed signature
    consumes the challenge but never returns a counter or creates privileges.
    """
    try:
        with transaction.atomic(durable=True):
            account = _operator_locked(operator)
            row = (
                OperatorWebAuthnChallenge.objects.select_for_update()
                .filter(pk=challenge_id, operator=account).first()
            )
            if row is None or row.closed_at is not None:
                raise PermissionDenied("WebAuthn challenge unavailable.")
            now = timezone.now()
            row.closed_at = now
            verified_counter = None
            credential_matches = False
            try:
                credential_matches = (
                    row.credential_id_digest == _credential_digest(credential_data)
                )
            except (ValueError, TypeError, AttributeError, KeyError):
                pass
            if (
                now < row.expires_at
                and row.rp_id == rp_id
                and row.origin == origin
                and credential_matches
            ):
                try:
                    verified_counter = verify_operator_assertion(
                        rp_id=rp_id, origin=origin, credential_data=credential_data,
                        state={
                            "challenge": row.challenge,
                            "user_verification": "required",
                        },
                        response=response, previous_sign_count=previous_sign_count,
                    )
                except (ValueError, TypeError, KeyError, AttributeError):
                    pass
            if verified_counter is not None:
                row.verified_at = now
            row.save(update_fields=["closed_at", "verified_at", "updated_at"])
    except (DatabaseError, RuntimeError):
        raise PermissionDenied("WebAuthn challenge storage unavailable.") from None
    if verified_counter is None:
        raise PermissionDenied("WebAuthn assertion rejected.")
    return verified_counter
