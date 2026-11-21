"""School-owned revocation of EXISTING aid access grants; no public API.

An explicitly assigned, authenticated school aid director can revoke only
grants belonging to that active school. The service cannot issue, reactivate,
change ownership of, or discover grants outside that school. Initial director
provisioning and verified household invitations are deliberately separate.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404

from .access import require_aid_director_access
from .models import (
    HouseholdAccess,
    School,
    SchoolGrantDecisionEvent,
    SchoolStaffAccess,
    VerifiedRecoveryContact,
)


def _lock_authorized_school(*, actor, school_id):
    """Check authorization, serialize school decisions, then re-check."""
    school = require_aid_director_access(actor, school_id=school_id)
    locked_school = School.objects.select_for_update().get(
        pk=school.pk, is_active=True
    )
    # Checking a second time prevents a stale check after acquiring the lock.
    require_aid_director_access(actor, school_id=locked_school.pk)
    return locked_school


def _record_revocation(*, school, actor, grant, kind, scope_id):
    """Write authenticated operator evidence in the same DB transaction."""
    SchoolGrantDecisionEvent.objects.create(
        school=school,
        actor_user=actor,
        target_user_id=grant.user_id,
        grant_kind=kind,
        grant_id=grant.pk,
        scope_id=scope_id,
        action=SchoolGrantDecisionEvent.ACTION_REVOKED,
    )


@transaction.atomic
def revoke_household_access(*, actor, school_id, household_id, subject_user_id):
    """Revoke an existing same-school family grant without creating access.

    Unknown, cross-school and inactive-household scopes are indistinguishable.
    A repeated revocation is a no-op and creates no duplicate operator event.
    """
    school = _lock_authorized_school(actor=actor, school_id=school_id)
    if not household_id or not subject_user_id:
        raise Http404("Grant not found.")
    grant = (
        HouseholdAccess.objects.select_for_update()
        .filter(
            household_id=household_id,
            household__school_id=school.pk,
            household__is_active=True,
            user_id=subject_user_id,
        )
        .first()
    )
    if grant is None:
        raise Http404("Grant not found.")
    if not grant.is_active:
        return grant
    grant.is_active = False
    grant.save(update_fields=["is_active", "updated_at"])
    _record_revocation(
        school=school,
        actor=actor,
        grant=grant,
        kind=SchoolGrantDecisionEvent.KIND_HOUSEHOLD,
        scope_id=grant.household_id,
    )
    return grant


@transaction.atomic
def revoke_staff_access(*, actor, school_id, subject_user_id):
    """Revoke an existing director, preserving one usable director per school.

    Directors administer their own school; Arete is not required to approve
    routine changes. The last active director cannot be removed through this
    service, including when attempting self-revocation.
    """
    school = _lock_authorized_school(actor=actor, school_id=school_id)
    if not subject_user_id:
        raise Http404("Grant not found.")
    grant = (
        SchoolStaffAccess.objects.for_school(school.pk)
        .select_for_update()
        .filter(
            user_id=subject_user_id,
            role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        )
        .first()
    )
    if grant is None:
        raise Http404("Grant not found.")
    if not grant.is_active:
        return grant
    remaining_director = (
        SchoolStaffAccess.objects.for_school(school.pk)
        .filter(
            is_active=True,
            role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
            user__is_active=True,
        )
        .exclude(pk=grant.pk)
        .exists()
    )
    if not remaining_director:
        raise ValidationError("Cannot revoke the school's last active aid director.")
    grant.is_active = False
    grant.save(update_fields=["is_active", "updated_at"])
    _record_revocation(
        school=school,
        actor=actor,
        grant=grant,
        kind=SchoolGrantDecisionEvent.KIND_STAFF,
        scope_id=school.pk,
    )
    return grant



@transaction.atomic
def grant_additional_director(*, actor, school_id, subject_user_id):
    """Grant a NEW director seat to an existing verified active user.

    A currently authorized director is required, so this cannot bootstrap
    the first director. Existing revoked grants are never reactivated.
    School locking serializes multiple administrators' decisions.
    """
    school = _lock_authorized_school(actor=actor, school_id=school_id)
    if not subject_user_id:
        raise Http404("Eligible staff account not found.")
    subject = get_user_model()._default_manager.select_for_update().filter(
        pk=subject_user_id, is_active=True,
    ).first()
    if subject is None:
        raise Http404("Eligible staff account not found.")
    # An email on User is not proof of control of a recovery mailbox.
    if not VerifiedRecoveryContact.objects.filter(
        user=subject, superseded_at__isnull=True,
    ).exists():
        raise ValidationError("Staff account requires a verified recovery contact.")
    if SchoolStaffAccess.objects.for_school(school.pk).filter(
        user=subject,
    ).exists():
        raise ValidationError("A school staff grant already exists; no reactivation.")

    grant = SchoolStaffAccess.objects.create(
        school=school,
        user=subject,
        role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
    )
    SchoolGrantDecisionEvent.objects.create(
        school=school,
        actor_user=actor,
        target_user=subject,
        grant_kind=SchoolGrantDecisionEvent.KIND_STAFF,
        grant_id=grant.pk,
        scope_id=school.pk,
        action=SchoolGrantDecisionEvent.ACTION_CREATED,
    )
    return grant
