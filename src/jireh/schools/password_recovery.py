"""Internal-only verified-contact password recovery for standalone Jireh.

NO public HTTP routes, no mailbox-provider configuration, no account discovery
API, no real customer email, and no production activation are provided.

A recovery contact must first be enrolled by a logged-in user with a fresh,
one-time mailbox code. Password recovery can then send a separate one-time
code ONLY to that contact, using the existing opt-in secure SMTP adapter.
Never treat the unaudited User.email field as a verified recovery channel.
"""

import hashlib
import hmac
import secrets
from datetime import timedelta
from math import ceil

from django.conf import settings
from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from .delivery import (
    DeliveryFailure, _require_secure_delivery, _send_one_secret,
)
from .login_budget import _identifier_digest
from .models import (
    MailboxChallenge, PasswordRecoveryChallenge, RecoveryAttemptBudget,
    RecoveryContactRotationEvent, VerifiedRecoveryContact,
)
from .redemption import _authenticated, _token_digest


RECOVERY_LIFETIME = timedelta(minutes=15)
RECOVERY_WINDOW = timedelta(minutes=15)
RECOVERY_MAX_ATTEMPTS = 10


def _validate_username(username):
    if (not isinstance(username, str)
            or not 1 <= len(username) <= 150
            or username != username.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in username)):
        raise ValidationError("Invalid recovery request.")
    return username


def _budget_key(username):
    # Purpose separation is also enforced by the composite DB key.
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        ("jireh-recovery-v1:" + _identifier_digest(username)).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


@transaction.atomic
def _charge(*, username, purpose):
    """Persist failed attempts even if later verification is rejected."""
    now = timezone.now()
    budget, _ = RecoveryAttemptBudget.objects.select_for_update().get_or_create(
        identifier_digest=_budget_key(username),
        purpose=purpose,
        defaults={"window_started_at": now, "attempt_count": 0},
    )
    expires = budget.window_started_at + RECOVERY_WINDOW
    if now >= expires:
        budget.window_started_at = now
        budget.attempt_count = 0
        expires = now + RECOVERY_WINDOW
    if budget.attempt_count >= RECOVERY_MAX_ATTEMPTS:
        return False, max(1, ceil((expires - now).total_seconds()))
    budget.attempt_count += 1
    budget.save(update_fields=[
        "window_started_at", "attempt_count", "updated_at",
    ])
    return True, 0


@transaction.atomic
def enroll_verified_recovery_contact(*, user, email, mailbox_token):
    """Consume a fresh delivered mailbox proof once; never trust user.email."""
    _authenticated(user)
    digest = _token_digest(mailbox_token)
    normalized = email.strip().casefold() if isinstance(email, str) else ""
    # The caller must possess a separate fresh mailbox code for this user.
    account = get_user_model()._default_manager.select_for_update().get(
        pk=user.pk, is_active=True,
    )
    if VerifiedRecoveryContact.objects.filter(
        user_id=account.pk, superseded_at__isnull=True,
    ).exists():
        raise ValidationError("A recovery contact is already enrolled.")
    now = timezone.now()
    proof = MailboxChallenge.objects.select_for_update().filter(
        user_id=account.pk,
        email=normalized,
        token_digest=digest,
        expires_at__gt=now,
        consumed_at__isnull=True,
    ).first()
    if proof is None:
        raise ValidationError("Invalid or expired mailbox proof.")
    proof.consumed_at = now
    proof.save(update_fields=["consumed_at", "updated_at"])
    return VerifiedRecoveryContact.objects.create(
        user=account, proof=proof, email=proof.email, verified_at=now,
    )


@transaction.atomic
def _prepare_recovery(*, username):
    """Return a temporary in-memory secret only for an enrolled active user.

    Lock the account to serialize this operation with password updates. A
    previous unconsumed recovery credential is consumed on reissue.
    """
    account = get_user_model()._default_manager.select_for_update().filter(
        username=username, is_active=True,
    ).first()
    if account is None:
        return None
    contact = VerifiedRecoveryContact.objects.filter(
        user=account, superseded_at__isnull=True,
    ).first()
    if contact is None:
        return None
    now = timezone.now()
    old = PasswordRecoveryChallenge.objects.select_for_update().filter(
        user=account, consumed_at__isnull=True,
    ).first()
    if old is not None:
        old.consumed_at = now
        old.save(update_fields=["consumed_at", "updated_at"])
    raw = secrets.token_urlsafe(48)
    challenge = PasswordRecoveryChallenge.objects.create(
        user=account,
        contact=contact,
        token_digest=_token_digest(raw),
        expires_at=now + RECOVERY_LIFETIME,
    )
    return challenge.pk, contact.email, raw


@transaction.atomic
def _cancel_challenge(*, challenge_id):
    credential = PasswordRecoveryChallenge.objects.select_for_update().get(
        pk=challenge_id
    )
    if credential.consumed_at is None:
        credential.consumed_at = timezone.now()
        credential.save(update_fields=["consumed_at", "updated_at"])


def request_password_recovery(*, username):
    """Always return the same generic outcome, without revealing account state.

    The secure SMTP policy must be explicitly enabled by a future approved
    environment. A failed/ambiguous send consumes its one-use secret. Both
    known and unknown identifiers are charged. This is an internal API only.
    """
    username = _validate_username(username)
    sender = _require_secure_delivery()
    allowed, _ = _charge(
        username=username, purpose=RecoveryAttemptBudget.PURPOSE_ISSUE,
    )
    if not allowed:
        return {"accepted": True}
    prepared = _prepare_recovery(username=username)
    if prepared is None:
        return {"accepted": True}
    challenge_id, recipient, raw = prepared
    try:
        _send_one_secret(
            to=recipient,
            token=raw,
            subject="Jireh Financial Aid password recovery",
            purpose="one-time password recovery",
            sender=sender,
        )
    except DeliveryFailure:
        try:
            _cancel_challenge(challenge_id=challenge_id)
        except Exception:
            # Does not expose the credential; an operational alert will be
            # required before customer activation.
            raise DeliveryFailure(
                "Jireh recovery cancellation requires review."
            ) from None
    return {"accepted": True}


def reset_password_with_recovery(*, username, token, new_password):
    """Use one credential once, validate password, atomically change hash.

    Django session authentication hashes invalidate all preexisting logged-in
    sessions following a password change; we never call
    update_session_auth_hash, which would preserve a current session.
    """
    username = _validate_username(username)
    allowed, _ = _charge(
        username=username, purpose=RecoveryAttemptBudget.PURPOSE_CONFIRM,
    )
    if not allowed:
        raise PermissionDenied("Recovery confirmation limit reached.")
    try:
        digest = _token_digest(token)
    except Http404:
        raise ValidationError("Invalid or expired recovery credential.") from None

    with transaction.atomic():
        account = get_user_model()._default_manager.select_for_update().filter(
            username=username, is_active=True,
        ).first()
        if account is None:
            raise ValidationError("Invalid or expired recovery credential.")
        now = timezone.now()
        credential = PasswordRecoveryChallenge.objects.select_for_update().filter(
            user=account,
            token_digest=digest,
            contact__superseded_at__isnull=True,
            consumed_at__isnull=True,
            expires_at__gt=now,
        ).first()
        if credential is None:
            raise ValidationError("Invalid or expired recovery credential.")
        # Do not pass malformed password types to Django's password hasher.
        if not isinstance(new_password, str) or not 1 <= len(new_password) <= 1024:
            raise ValidationError("Invalid new password.")
        password_validation.validate_password(new_password, user=account)
        account.set_password(new_password)
        account.save(update_fields=["password"])
        credential.consumed_at = now
        credential.password_changed_at = now
        credential.save(update_fields=[
            "consumed_at", "password_changed_at", "updated_at",
        ])
    return {"password_changed": True}



def rotate_verified_recovery_contact(
    *, user, current_password, old_mailbox_token,
    new_email, new_mailbox_token,
):
    """Change the current recovery mailbox without deleting historical evidence.

    Requires a fresh account password and two separately issued one-use
    mailbox codes: one for the current verified contact, another for the
    replacement. The account lock serializes rotation with password reset
    and recovery issuance. Old recovery codes become unusable immediately.
    """
    _authenticated(user)
    if not isinstance(current_password, str) or not 1 <= len(current_password) <= 1024:
        raise PermissionDenied("Rotation credentials invalid.")
    old_digest = _token_digest(old_mailbox_token)
    new_digest = _token_digest(new_mailbox_token)
    if old_digest == new_digest:
        raise ValidationError("Distinct mailbox proofs are required.")
    from .invitations import _normalize_recipient
    normalized = _normalize_recipient(new_email)
    allowed, _ = _charge(
        username=user.get_username(),
        purpose=RecoveryAttemptBudget.PURPOSE_CONFIRM,
    )
    if not allowed:
        raise PermissionDenied("Contact rotation attempt limit reached.")

    with transaction.atomic():
        account = get_user_model()._default_manager.select_for_update().filter(
            pk=user.pk, is_active=True,
        ).first()
        if account is None or not account.check_password(current_password):
            raise PermissionDenied("Rotation credentials invalid.")
        current = VerifiedRecoveryContact.objects.select_for_update().filter(
            user=account, superseded_at__isnull=True,
        ).first()
        if current is None or current.email == normalized:
            raise ValidationError("A distinct verified contact is required.")
        now = timezone.now()
        old_proof = MailboxChallenge.objects.select_for_update().filter(
            user=account, email=current.email, token_digest=old_digest,
            consumed_at__isnull=True, expires_at__gt=now,
        ).first()
        new_proof = MailboxChallenge.objects.select_for_update().filter(
            user=account, email=normalized, token_digest=new_digest,
            consumed_at__isnull=True, expires_at__gt=now,
        ).first()
        if old_proof is None or new_proof is None:
            raise ValidationError("Invalid or expired mailbox proofs.")
        # Consume both mailbox credentials; rollback preserves them if
        # anything else in the rotation transaction fails.
        for proof in (old_proof, new_proof):
            proof.consumed_at = now
            proof.save(update_fields=["consumed_at", "updated_at"])
        current.superseded_at = now
        current.save(update_fields=["superseded_at", "updated_at"])
        # Reissue cannot race rotation: all recovery mutations lock account.
        for pending in PasswordRecoveryChallenge.objects.select_for_update().filter(
            user=account, consumed_at__isnull=True,
        ):
            pending.consumed_at = now
            pending.save(update_fields=["consumed_at", "updated_at"])
        replacement = VerifiedRecoveryContact.objects.create(
            user=account, proof=new_proof, email=normalized, verified_at=now,
        )
        RecoveryContactRotationEvent.objects.create(
            user=account, actor=account,
            old_contact=current, new_contact=replacement,
        )
    return replacement
