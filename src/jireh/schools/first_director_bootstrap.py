"""Disabled-by-default, dual-operator *internal* first-director bootstrap.

This is not school provisioning, user creation, an HTTP route, or a public
operator console. Trusted callers must independently authenticate the
operators and verify the external authorization reference. Both operators
also re-enter their own current passwords here; IDs and superuser status
alone never authorize a grant.
"""

import re
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.http import Http404
from django.utils import timezone

from .login_budget import charge_bootstrap_operator_attempt
from .models import (
    FirstDirectorBootstrapRequest, School, SchoolGrantDecisionEvent,
    SchoolStaffAccess, VerifiedRecoveryContact,
)


BOOTSTRAP_LIFETIME = timedelta(minutes=15)
REFERENCE_RE = re.compile(r"\A[A-Z0-9][A-Z0-9-]{7,119}\Z")


def _charge_operator_attempt(operator):
    """Commit an attempt before the grant transaction; reject outer rollback."""
    if getattr(settings, "JIREH_FIRST_DIRECTOR_BOOTSTRAP_ENABLED", False) is not True:
        raise PermissionDenied("Initial director bootstrap disabled.")
    allowlist = getattr(settings, "JIREH_BOOTSTRAP_OPERATOR_IDS", ())
    if (not isinstance(allowlist, (tuple, frozenset))
            or len(allowlist) < 2
            or len(set(allowlist)) != len(allowlist)
            or getattr(operator, "pk", None) not in allowlist):
        raise PermissionDenied("Operator authentication required.")
    try:
        with transaction.atomic(durable=True):
            allowed, _ = charge_bootstrap_operator_attempt(operator_id=operator.pk)
    except (DatabaseError, RuntimeError):
        raise PermissionDenied("Operator attempt control unavailable.") from None
    if not allowed:
        raise PermissionDenied("Operator attempt limit exceeded.")


def _operator(*, user, password):
    if getattr(settings, "JIREH_FIRST_DIRECTOR_BOOTSTRAP_ENABLED", False) is not True:
        raise PermissionDenied("Initial director bootstrap disabled.")
    allowlist = getattr(settings, "JIREH_BOOTSTRAP_OPERATOR_IDS", ())
    if (not isinstance(allowlist, (tuple, frozenset))
            or len(allowlist) < 2
            or len(set(allowlist)) != len(allowlist)):
        raise PermissionDenied("Initial director operators are not configured.")
    if (not getattr(user, "is_authenticated", False)
            or not getattr(user, "is_active", False)
            or not getattr(user, "is_staff", False)
            or not getattr(user, "is_superuser", False)
            or user.pk not in allowlist
            or not isinstance(password, str)
            or not 1 <= len(password) <= 1024):
        raise PermissionDenied("Operator authentication required.")
    account = get_user_model()._default_manager.select_for_update().filter(
        pk=user.pk, is_active=True, is_staff=True, is_superuser=True,
    ).first()
    if account is None or not account.check_password(password):
        raise PermissionDenied("Operator authentication required.")
    return account


def _available_school(*, school_id):
    school = School.objects.select_for_update().filter(
        pk=school_id, is_active=True,
    ).first()
    if school is None:
        raise Http404("School not found.")
    # No bootstrap after ANY historical director grant, including revoked.
    if SchoolStaffAccess.objects.for_school(school.pk).exists():
        raise ValidationError("School already has director-grant history.")
    return school


def propose_first_director(
    *, operator, operator_password, school_id, subject_user_id,
    authorization_reference,
):
    """Debit operator budget independently before starting grant work."""
    _charge_operator_attempt(operator)
    return _propose_first_director(
        operator=operator, operator_password=operator_password,
        school_id=school_id, subject_user_id=subject_user_id,
        authorization_reference=authorization_reference,
    )


@transaction.atomic
def _propose_first_director(
    *, operator, operator_password, school_id, subject_user_id,
    authorization_reference,
):
    """Prepare a short-lived, actor-attributed request; never grant access."""
    if not isinstance(authorization_reference, str) or not REFERENCE_RE.fullmatch(
        authorization_reference
    ):
        raise ValidationError("A bounded external authorization reference is required.")
    actor = _operator(user=operator, password=operator_password)
    school = _available_school(school_id=school_id)
    subject = get_user_model()._default_manager.select_for_update().filter(
        pk=subject_user_id, is_active=True,
    ).first()
    if subject is None or subject.pk == actor.pk:
        raise Http404("Eligible director account not found.")
    if subject.is_superuser or subject.is_staff:
        raise ValidationError("Bootstrap candidate must be a nonprivileged account.")
    if not VerifiedRecoveryContact.objects.filter(
        user=subject, superseded_at__isnull=True,
    ).exists():
        raise ValidationError("Candidate requires a verified recovery contact.")

    now = timezone.now()
    prior = FirstDirectorBootstrapRequest.objects.select_for_update().filter(
        school=school, approved_at__isnull=True, closed_at__isnull=True,
    ).first()
    if prior is not None:
        if prior.expires_at > now:
            raise ValidationError("A pending director proposal already exists.")
        prior.closed_at = now
        prior.save(update_fields=["closed_at", "updated_at"])

    return FirstDirectorBootstrapRequest.objects.create(
        school=school,
        subject=subject,
        proposed_by=actor,
        authorization_reference=authorization_reference,
        expires_at=now + BOOTSTRAP_LIFETIME,
    )


def approve_first_director(
    *, operator, operator_password, request_id, authorization_reference,
):
    """Independently debit the approving operator's attempt budget."""
    _charge_operator_attempt(operator)
    return _approve_first_director(
        operator=operator, operator_password=operator_password,
        request_id=request_id, authorization_reference=authorization_reference,
    )


@transaction.atomic
def _approve_first_director(
    *, operator, operator_password, request_id, authorization_reference,
):
    """Confirm with a *different* operator and atomically grant and audit.

    Caller must independently confirm that the external reference is valid
    and approved by the school; merely knowing its value is not proof of
    institutional consent. This service never auto-selects or creates users.
    """
    if not isinstance(authorization_reference, str) or not REFERENCE_RE.fullmatch(
        authorization_reference
    ):
        raise ValidationError("An external authorization reference is required.")
    actor = _operator(user=operator, password=operator_password)
    proposal = FirstDirectorBootstrapRequest.objects.filter(
        pk=request_id,
    ).first()
    if proposal is None:
        raise Http404("Initial director proposal not found.")
    school = _available_school(school_id=proposal.school_id)
    locked = FirstDirectorBootstrapRequest.objects.select_for_update().filter(
        pk=request_id, school=school,
    ).first()
    if locked is None or locked.closed_at is not None or locked.approved_at is not None:
        raise ValidationError("Initial director proposal is no longer pending.")
    if locked.expires_at <= timezone.now():
        raise ValidationError("Initial director proposal has expired.")
    if locked.authorization_reference != authorization_reference:
        raise PermissionDenied("Initial director authorization mismatch.")
    if actor.pk in (locked.proposed_by_id, locked.subject_id):
        raise PermissionDenied("Distinct operator and subject are required.")
    subject = get_user_model()._default_manager.select_for_update().filter(
        pk=locked.subject_id, is_active=True, is_staff=False, is_superuser=False,
    ).first()
    if subject is None or not VerifiedRecoveryContact.objects.filter(
        user=subject, superseded_at__isnull=True,
    ).exists():
        raise ValidationError("Director candidate is no longer eligible.")
    # Re-read under school lock. A previous staff grant is never reactivated.
    if SchoolStaffAccess.objects.for_school(school.pk).exists():
        raise ValidationError("Director grant already exists.")

    grant = SchoolStaffAccess.objects.create(
        school=school,
        user=subject,
        role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
    )
    now = timezone.now()
    locked.approved_by = actor
    locked.approved_at = now
    locked.grant = grant
    locked.save(update_fields=["approved_by", "approved_at", "grant", "updated_at"])
    SchoolGrantDecisionEvent.objects.create(
        school=school, actor_user=actor, target_user=subject,
        grant_kind=SchoolGrantDecisionEvent.KIND_STAFF,
        grant_id=grant.pk, scope_id=school.pk,
        action=SchoolGrantDecisionEvent.ACTION_CREATED,
    )
    return grant
