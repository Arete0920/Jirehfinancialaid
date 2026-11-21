"""Internal-only mailbox challenge and atomic household invitation redemption.

This module deliberately has NO HTTP routes and NO email sender. A trustworthy
delivery adapter must send the mailbox token to the target address; merely
generating or presenting one does NOT certify mailbox ownership. The caller
must be Django-authenticated and must possess BOTH independently delivered
opaque secrets. Neither user.email nor an invitation's email implies access.
"""

import hashlib
import secrets
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from .invitations import _normalize_recipient
from .models import (
    HouseholdAccess, HouseholdInvitation, MailboxChallenge, School,
    SchoolInvitationEvent,
)


MAILBOX_PROOF_LIFETIME = timedelta(minutes=15)


def _authenticated(user):
    if not getattr(user, "is_authenticated", False) or not getattr(
        user, "is_active", False
    ) or getattr(user, "pk", None) is None:
        raise PermissionDenied("Authentication required.")


def _token_digest(token):
    """Require a high-entropy URL-safe token shape before database lookup."""
    if not isinstance(token, str) or len(token) != 64:
        raise Http404("Invitation not found.")
    if any(char not in (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    ) for char in token):
        raise Http404("Invitation not found.")
    return hashlib.sha256(token.encode("ascii")).hexdigest()


@transaction.atomic
def issue_mailbox_challenge(*, user, email):
    """Internal preparation for trusted delivery, NOT delivery or verification.

    A 48-byte random proof must ONLY be sent to the designated mailbox by
    an independently authenticated delivery adapter. No public endpoint is
    wired and no application is authorized by calling this service.
    """
    _authenticated(user)
    normalized = _normalize_recipient(email)
    now = timezone.now()
    existing = (
        MailboxChallenge.objects.select_for_update()
        .filter(user_id=user.pk, email=normalized, consumed_at__isnull=True)
        .first()
    )
    if existing is not None:
        if existing.expires_at > now:
            raise ValidationError("A mailbox challenge is already pending.")
        existing.consumed_at = now
        existing.save(update_fields=["consumed_at", "updated_at"])

    token = secrets.token_urlsafe(48)
    challenge = MailboxChallenge.objects.create(
        user=user,
        email=normalized,
        token_digest=_token_digest(token),
        expires_at=now + MAILBOX_PROOF_LIFETIME,
    )
    return challenge, token


@transaction.atomic
def redeem_household_invitation(
    *, user, school_id, household_id, invitation_token, mailbox_token
):
    """One-use grant requiring independent invitation AND mailbox proofs.

    The mailbox challenge is bound to the authenticated account and the
    invitation's exact recipient. The two secrets are hashed, never stored
    in plaintext. A school row lock serializes school-scoped administrative
    mutations with invitation redemption. No existing grant is reactivated.
    All state updates and audit evidence are committed together or not at all.
    """
    _authenticated(user)
    invite_digest = _token_digest(invitation_token)
    mailbox_digest = _token_digest(mailbox_token)
    if not school_id or not household_id:
        raise Http404("Invitation not found.")

    school = School.objects.select_for_update().filter(
        pk=school_id, is_active=True
    ).first()
    if school is None:
        raise Http404("Invitation not found.")

    invitation = (
        HouseholdInvitation.objects.for_school(school.pk)
        .select_for_update()
        .filter(
            household_id=household_id,
            household__school_id=school.pk,
            household__is_active=True,
            token_digest=invite_digest,
            revoked_at__isnull=True,
            redeemed_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .first()
    )
    if invitation is None:
        raise Http404("Invitation not found.")

    proof = (
        MailboxChallenge.objects.select_for_update()
        .filter(
            user_id=user.pk,
            email=invitation.email,
            token_digest=mailbox_digest,
            consumed_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .first()
    )
    if proof is None:
        raise Http404("Invitation not found.")

    if HouseholdAccess.objects.filter(
        household_id=invitation.household_id, user_id=user.pk
    ).exists():
        raise ValidationError(
            "A household grant already exists. This flow cannot reactivate it."
        )

    now = timezone.now()
    if invitation.expires_at <= now or proof.expires_at <= now:
        raise Http404("Invitation not found.")

    access = HouseholdAccess.objects.create(
        household_id=invitation.household_id, user=user
    )
    invitation.redeemed_at = now
    invitation.redeemed_by = user
    invitation.save(update_fields=["redeemed_at", "redeemed_by", "updated_at"])

    proof.consumed_at = now
    proof.save(update_fields=["consumed_at", "updated_at"])

    SchoolInvitationEvent.objects.create(
        school=school,
        invitation=invitation,
        actor_user=user,
        action=SchoolInvitationEvent.ACTION_REDEEMED,
    )
    return access
