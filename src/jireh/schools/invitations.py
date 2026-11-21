"""School-owned issuance/cancellation of pending household invitations.

No email transport, public redemption endpoint, identity match or access-grant
creation exists in this module. A token is returned exactly once to a trusted
caller and only its SHA-256 digest is stored. Delivery and redemption must be
implemented with verified identity controls before this can serve real users.
"""

import hashlib
import secrets
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from .grant_admin import _lock_authorized_school
from .models import Household, HouseholdInvitation, SchoolInvitationEvent


INVITATION_LIFETIME = timedelta(hours=24)


def _normalize_recipient(email):
    if not isinstance(email, str):
        raise ValidationError({"email": "A recipient email address is required."})
    normalized = email.strip().casefold()
    if not normalized or len(normalized) > 254:
        raise ValidationError({"email": "A valid recipient email address is required."})
    return normalized


def _audit(*, school, invitation, actor, action):
    SchoolInvitationEvent.objects.create(
        school=school,
        invitation=invitation,
        actor_user=actor,
        action=action,
    )


def _revoke(*, school, invitation, actor, now):
    """Idempotent state transition and actor audit in caller's transaction."""
    if invitation.revoked_at is not None or invitation.redeemed_at is not None:
        return False
    invitation.revoked_at = now
    invitation.save(update_fields=["revoked_at", "updated_at"])
    _audit(
        school=school,
        invitation=invitation,
        actor=actor,
        action=SchoolInvitationEvent.ACTION_REVOKED,
    )
    return True


@transaction.atomic
def issue_household_invitation(*, actor, school_id, household_id, email):
    """Issue a pending invitation from an authorized school director.

    Only an active household in the director's own active school is eligible.
    The returned secret is never logged or persisted. Reissuing to the same
    recipient requires cancelling the previous live invitation; expired
    pending records are revoked and audited before a new issuance.
    """
    school = _lock_authorized_school(actor=actor, school_id=school_id)
    if not household_id:
        raise Http404("Household not found.")
    household = (
        Household.objects.for_school(school.pk)
        .select_for_update()
        .filter(pk=household_id, is_active=True)
        .first()
    )
    if household is None:
        raise Http404("Household not found.")

    recipient = _normalize_recipient(email)
    now = timezone.now()
    pending = (
        HouseholdInvitation.objects.for_school(school.pk)
        .select_for_update()
        .filter(
            household=household, email=recipient,
            revoked_at__isnull=True, redeemed_at__isnull=True,
        )
        .first()
    )
    if pending is not None:
        if pending.expires_at > now:
            raise ValidationError("A pending invitation already exists.")
        _revoke(school=school, invitation=pending, actor=actor, now=now)

    raw_token = secrets.token_urlsafe(48)
    digest = hashlib.sha256(raw_token.encode("ascii")).hexdigest()
    invitation = HouseholdInvitation.objects.create(
        school=school,
        household=household,
        email=recipient,
        token_digest=digest,
        expires_at=now + INVITATION_LIFETIME,
        invited_by=actor,
    )
    _audit(
        school=school,
        invitation=invitation,
        actor=actor,
        action=SchoolInvitationEvent.ACTION_ISSUED,
    )
    return invitation, raw_token


@transaction.atomic
def revoke_household_invitation(*, actor, school_id, invitation_id):
    """Cancel a pending invitation, never creating or reactivating a grant."""
    school = _lock_authorized_school(actor=actor, school_id=school_id)
    if not invitation_id:
        raise Http404("Invitation not found.")
    invitation = (
        HouseholdInvitation.objects.for_school(school.pk)
        .select_for_update()
        .filter(
            pk=invitation_id,
            household__school_id=school.pk,
        )
        .first()
    )
    if invitation is None:
        raise Http404("Invitation not found.")
    _revoke(
        school=school, invitation=invitation, actor=actor, now=timezone.now()
    )
    return invitation
