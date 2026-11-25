"""Internal, disabled WebAuthn proof bound to one privileged action.

Verified key possession is not permission to provision a school or grant a
director role. Consume the action-specific proof only inside the eventual
authorized business transaction, so a failed operation rolls back consumption.
School setup and director actions use distinct action and digest domains.
"""

import hashlib
import json
import re
from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from .models import (
    OperatorWebAuthnActionIntent,
    OperatorWebAuthnChallenge,
    OperatorWebAuthnCredential,
    SchoolSetupIntent,
)
from .operator_webauthn_challenges import _operator_locked
from .operator_webauthn_registry import (
    begin_registered_operator_challenge,
    complete_registered_operator_challenge,
)


_REFERENCE = re.compile(r"\A[A-Z0-9][A-Z0-9-]{7,119}\Z")
_DIGEST = re.compile(r"\A[0-9a-f]{64}\Z")
_DIRECTOR_ACTIONS = (
    OperatorWebAuthnActionIntent.ACTION_DIRECTOR_PROPOSE,
    OperatorWebAuthnActionIntent.ACTION_DIRECTOR_APPROVE,
)
_SETUP_ACTIONS = (
    OperatorWebAuthnActionIntent.ACTION_SETUP_PROPOSE,
    OperatorWebAuthnActionIntent.ACTION_SETUP_APPROVE,
)


def _enabled():
    if getattr(settings, "JIREH_OPERATOR_ACTION_MFA_ENABLED", False) is not True:
        raise PermissionDenied("Privileged action WebAuthn evidence disabled.")


def _uuid(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise PermissionDenied("Action context identifier invalid.") from None


def _subject_identifier(value):
    # Current Django auth PKs are positive integers; support canonical UUID
    # subject identities as well without equating numeric and UUID strings.
    if type(value) is int and 0 < value <= 9223372036854775807:
        return "int:" + str(value)
    return "uuid:" + _uuid(value)


def director_action_digest(
    *, action, authorization_reference,
    school_id=None, subject_user_id=None, request_id=None,
):
    """Produce identical, domain-separated digests at issuance and consumption."""
    if (not isinstance(authorization_reference, str)
            or not _REFERENCE.fullmatch(authorization_reference)):
        raise PermissionDenied("External authorization reference invalid.")
    if action == OperatorWebAuthnActionIntent.ACTION_DIRECTOR_PROPOSE:
        if school_id is None or subject_user_id is None or request_id is not None:
            raise PermissionDenied("Director proposal scope invalid.")
        context = {
            "action": action, "school_id": _uuid(school_id),
            "subject_user_id": _subject_identifier(subject_user_id),
            "authorization_reference": authorization_reference,
        }
    elif action == OperatorWebAuthnActionIntent.ACTION_DIRECTOR_APPROVE:
        if request_id is None or school_id is not None or subject_user_id is not None:
            raise PermissionDenied("Director approval scope invalid.")
        context = {
            "action": action, "request_id": _uuid(request_id),
            "authorization_reference": authorization_reference,
        }
    else:
        raise PermissionDenied("Unsupported privileged action.")
    payload = json.dumps(context, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(
        b"jireh-privileged-director-action-v1\x00" + payload.encode("utf-8")
    ).hexdigest()


def begin_director_action_proof(
    *, operator, credential_id_digest, action,
    authorization_reference, school_id=None, subject_user_id=None,
    request_id=None,
):
    """Issue a verified-key challenge before disclosing options to the caller."""
    _enabled()
    digest = director_action_digest(
        action=action, authorization_reference=authorization_reference,
        school_id=school_id, subject_user_id=subject_user_id,
        request_id=request_id,
    )
    return _begin_action_proof(
        operator=operator, credential_id_digest=credential_id_digest,
        action=action, digest=digest,
    )


def _begin_action_proof(*, operator, credential_id_digest, action, digest):
    options, challenge_id = begin_registered_operator_challenge(
        operator=operator, credential_id_digest=credential_id_digest,
    )
    try:
        with transaction.atomic(durable=True):
            account = _operator_locked(operator)
            challenge = (
                OperatorWebAuthnChallenge.objects.select_for_update()
                .filter(pk=challenge_id, operator=account, closed_at__isnull=True)
                .first()
            )
            if challenge is None or challenge.expires_at <= timezone.now():
                raise PermissionDenied("WebAuthn action challenge unavailable.")
            intent = OperatorWebAuthnActionIntent.objects.create(
                operator=account, challenge=challenge,
                action=action, payload_digest=digest,
                expires_at=challenge.expires_at,
            )
            return options, intent.pk
    except (DatabaseError, RuntimeError):
        raise PermissionDenied("WebAuthn action evidence unavailable.") from None


def complete_director_action_proof(*, operator, intent_id, response):
    """Verify the intended challenge, without authorizing its target action."""
    _enabled()
    return _complete_action_proof(
        operator=operator, intent_id=intent_id, response=response,
        allowed_actions=_DIRECTOR_ACTIONS,
    )


def _complete_action_proof(*, operator, intent_id, response, allowed_actions):
    try:
        with transaction.atomic(durable=True):
            account = _operator_locked(operator)
            intent = (
                OperatorWebAuthnActionIntent.objects.select_for_update()
                .select_related("challenge")
                .filter(pk=intent_id, operator=account, consumed_at__isnull=True,
                        action__in=allowed_actions)
                .first()
            )
            if (
                intent is None or intent.expires_at <= timezone.now()
                or intent.challenge.closed_at is not None
                or intent.challenge.verified_at is not None
            ):
                raise PermissionDenied("Pending action challenge unavailable.")
            challenge_id = intent.challenge_id
    except (DatabaseError, RuntimeError):
        raise PermissionDenied("WebAuthn action evidence unavailable.") from None
    return complete_registered_operator_challenge(
        operator=operator, challenge_id=challenge_id, response=response,
    )


def consume_director_action_proof(
    *, operator, intent_id, action, authorization_reference,
    school_id=None, subject_user_id=None, request_id=None,
):
    """One-use proof consumption; MUST share the future grant transaction.

    Explicitly NOT a grant, login, MFA certificate, or authorization decision.
    This service does not change first-director bootstrap in this milestone.
    """
    _enabled()
    if not connection.in_atomic_block:
        raise PermissionDenied("Privileged action evidence needs grant transaction.")
    digest = director_action_digest(
        action=action, authorization_reference=authorization_reference,
        school_id=school_id, subject_user_id=subject_user_id,
        request_id=request_id,
    )
    account = _operator_locked(operator)
    return _consume_action_proof(
        account=account, intent_id=intent_id, action=action, digest=digest,
    )


def _consume_action_proof(*, account, intent_id, action, digest):
    intent = (
        OperatorWebAuthnActionIntent.objects.select_for_update()
        .filter(pk=intent_id, operator=account, action=action,
                payload_digest=digest, consumed_at__isnull=True)
        .first()
    )
    if intent is None:
        raise PermissionDenied("Action-specific WebAuthn proof required.")
    challenge = (
        OperatorWebAuthnChallenge.objects.select_for_update()
        .filter(pk=intent.challenge_id, operator=account).first()
    )
    now = timezone.now()
    if (
        challenge is None or challenge.verified_at is None
        or challenge.closed_at is None
        or challenge.verified_at > now
        or challenge.verified_at > intent.expires_at
        or intent.expires_at <= now
    ):
        raise PermissionDenied("Fresh verified WebAuthn action proof required.")
    credential = (
        OperatorWebAuthnCredential.objects.select_for_update()
        .filter(operator=account,
                credential_id_digest=challenge.credential_id_digest,
                enrollment_verified_at__isnull=False,
                revoked_at__isnull=True).first()
    )
    if credential is None:
        raise PermissionDenied("Approved active credential required.")
    intent.consumed_at = now
    intent.save(update_fields=["consumed_at", "updated_at"])
    return intent.pk


def _setup_enabled():
    _enabled()
    if getattr(settings, "JIREH_SCHOOL_SETUP_ACTION_MFA_ENABLED", False) is not True:
        raise PermissionDenied("School setup WebAuthn evidence disabled.")


def _setup_uuid(value):
    try:
        if not isinstance(value, (str, UUID)):
            raise ValueError
        identifier = UUID(str(value))
        if not identifier.int or str(identifier) != str(value):
            raise ValueError
        return identifier
    except (ValueError, TypeError, AttributeError):
        raise PermissionDenied("School setup identifier invalid.") from None


def _setup_action_digest(*, operator_id, action, setup_intent_id,
                         authorization_reference, lock=False):
    if (type(action) is not str or action not in _SETUP_ACTIONS
            or not isinstance(authorization_reference, str)
            or not _REFERENCE.fullmatch(authorization_reference)
            or operator_id is None):
        raise PermissionDenied("School setup action context invalid.")
    identifier = _setup_uuid(setup_intent_id)
    try:
        receipts = SchoolSetupIntent.objects.all()
        if lock:
            receipts = receipts.select_for_update()
        receipt = receipts.filter(pk=identifier).first()
    except DatabaseError:
        raise PermissionDenied("School setup receipt unavailable.") from None
    if (receipt is None or not _DIGEST.fullmatch(receipt.candidate_digest)
            or not receipt.idempotency_key.int):
        raise PermissionDenied("School setup receipt unavailable.")
    is_owner = receipt.proposed_by_id == operator_id
    if is_owner != (action == OperatorWebAuthnActionIntent.ACTION_SETUP_PROPOSE):
        raise PermissionDenied("School setup action operator denied.")
    context = [
        action, str(receipt.pk), str(receipt.idempotency_key),
        _subject_identifier(receipt.proposed_by_id), receipt.candidate_digest,
        authorization_reference,
    ]
    payload = json.dumps(context, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(
        b"jireh-privileged-school-setup-action-v1\x00" + payload.encode("ascii")
    ).hexdigest()


def begin_setup_action_proof(
    *, operator, credential_id_digest, action, setup_intent_id,
    authorization_reference,
):
    """Bind a verified-key challenge to an existing immutable setup receipt.

    Only the receipt owner may prove the proposal action; approval requires
    a distinct eligible operator. No school is created or authorized here.
    """
    _setup_enabled()
    digest = _setup_action_digest(
        operator_id=getattr(operator, "pk", None), action=action,
        setup_intent_id=setup_intent_id,
        authorization_reference=authorization_reference,
    )
    return _begin_action_proof(
        operator=operator, credential_id_digest=credential_id_digest,
        action=action, digest=digest,
    )


def complete_setup_action_proof(*, operator, intent_id, response):
    """Verify only a setup challenge, never a director-action challenge."""
    _setup_enabled()
    return _complete_action_proof(
        operator=operator, intent_id=_setup_uuid(intent_id), response=response,
        allowed_actions=_SETUP_ACTIONS,
    )


def consume_setup_action_proof(
    *, operator, intent_id, action, setup_intent_id, authorization_reference,
):
    """Consume one exact receipt-bound proof inside a future transaction.

    The caller must independently verify the external authorization reference,
    preparation and code availability, and consume BOTH distinct operators'
    proofs atomically with the separately approved business operation.
    This primitive neither accepts a school setup nor grants provisioning.
    """
    _setup_enabled()
    if not connection.in_atomic_block:
        raise PermissionDenied("School setup evidence needs an authorized transaction.")
    account = _operator_locked(operator)
    digest = _setup_action_digest(
        operator_id=account.pk, action=action, setup_intent_id=setup_intent_id,
        authorization_reference=authorization_reference, lock=True,
    )
    return _consume_action_proof(
        account=account, intent_id=_setup_uuid(intent_id), action=action,
        digest=digest,
    )
