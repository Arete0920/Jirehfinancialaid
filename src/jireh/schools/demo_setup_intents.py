"""Disposable-test rehearsal of immutable setup intent persistence.

Only the explicit disposable operator preparation adapter may call this
service from the independent operations router. No school creation,
activation, job runner, payment, or SIS integration occurs here. A separate disposable
provisioning rehearsal can opt into the same validator and receipt with an
allowlisted operator; production authorization remains separate.
"""

import hashlib
import json
import os
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction

from .demo_platform_operations import _authorized_operator
from .models import SchoolSetupIntent
from .operator_webauthn_challenges import _operator_locked
from .school_setup_preflight import (
    SchoolSetupPreflightError,
    validate_school_setup_candidate,
)


_TEST_SETTINGS = frozenset((
    "jireh.schools.test_settings",
    "jireh.schools.postgres_test_settings",
))


def _candidate_evidence(payload, *, privileged=False):
    """Validate the proposal and derive its immutable V1 request identity."""
    try:
        candidate = validate_school_setup_candidate(payload)
    except SchoolSetupPreflightError:
        raise ValidationError("Invalid school setup proposal.") from None

    if privileged and not candidate.code.startswith("synthetic-"):
        raise ValidationError("Synthetic setup requires a fictional school code.")

    # Verify the exact zone key is available and loadable on this test host.
    # This is deliberately not a decision to normalize aliases or a canonical
    # production timezone registry. Missing timezone data fails closed.
    try:
        if candidate.timezone not in available_timezones():
            raise ZoneInfoNotFoundError(candidate.timezone)
        ZoneInfo(candidate.timezone)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ValidationError("Setup timezone unavailable.") from None

    # Fixed order and explicit version prevent ambiguity and silent digest
    # format drift. Include every accepted field, including the request UUID.
    # Retain only the digest, never the candidate's plaintext attributes.
    canonical = json.dumps(
        ["jireh.school-setup-intent.v1", candidate.code, candidate.name,
         candidate.timezone, candidate.idempotency_key],
        ensure_ascii=True, separators=(",", ":"), allow_nan=False,
    ).encode("ascii")
    return UUID(candidate.idempotency_key), hashlib.sha256(canonical).hexdigest()


def _require_setup_context(operator, *, privileged=False):
    """Keep the non-superuser demo and privileged test paths distinct."""
    startup = os.environ.get("DJANGO_SETTINGS_MODULE")
    if (startup not in _TEST_SETTINGS
            or settings.SETTINGS_MODULE not in (None, startup)
            or getattr(settings, "JIREH_SYNTHETIC_SETUP_INTENT_ONLY", False) is not True
            or not isinstance(operator, get_user_model())
            or type(privileged) is not bool):
        raise PermissionDenied("Synthetic setup preparation disabled or denied.")
    if privileged:
        if (settings.ROOT_URLCONF != "jireh.schools.urls"
                or getattr(settings, "JIREH_SYNTHETIC_PROVISIONING_ONLY", False) is not True
                or getattr(settings, "JIREH_SCHOOL_SETUP_ACTION_MFA_ENABLED", False) is not True
                or getattr(settings, "JIREH_OPERATOR_ACTION_MFA_ENABLED", False) is not True):
            raise PermissionDenied("Privileged setup rehearsal disabled.")
    elif not _authorized_operator(operator):
        raise PermissionDenied("Synthetic setup preparation disabled or denied.")


def _locked_setup_operator(operator, *, privileged=False):
    if privileged:
        # The registry guard requires an explicit two-operator allowlist and
        # rechecks active persisted operator authority under the row lock.
        return _operator_locked(operator)
    account = get_user_model()._default_manager.select_for_update().filter(
        pk=operator.pk,
    ).first()
    if account is None or not _authorized_operator(account):
        raise PermissionDenied("Synthetic setup preparation denied.")
    return account


def _require_setup_write_context(operator, payload, *, privileged=False, portal_request=None):
    """Keep provisioning guards intact; admit only the exact preparation request."""
    if portal_request is None:
        _require_setup_context(operator, privileged=privileged)
        return
    if privileged is not True:
        raise PermissionDenied("Privileged preparation rehearsal required.")
    from jireh.runtime.operator_preparation import require_preparation_request

    require_preparation_request(portal_request, operator=operator, payload=payload)


def record_synthetic_setup_intent(*, operator, payload, privileged=False, portal_request=None):
    """Persist one fictional receipt; only exact owned replay is accepted.

    The optional privileged path is internal to disposable provisioning tests.
    It never changes the authorization requirements of the demo dashboard.
    """
    _require_setup_write_context(operator, payload, privileged=privileged, portal_request=portal_request)
    idempotency_key, candidate_digest = _candidate_evidence(
        payload, privileged=privileged,
    )
    try:
        with transaction.atomic(durable=True):
            account = _locked_setup_operator(operator, privileged=privileged)
            if portal_request is not None:
                _require_setup_write_context(account, payload, privileged=privileged, portal_request=portal_request)
            receipt, _ = SchoolSetupIntent.objects.get_or_create(
                idempotency_key=idempotency_key,
                defaults={
                    "proposed_by": account,
                    "candidate_digest": candidate_digest,
                },
            )
            if (receipt.proposed_by_id != account.pk
                    or receipt.candidate_digest != candidate_digest):
                raise PermissionDenied("Setup request replay denied.")
            return receipt
    except DatabaseError:
        raise PermissionDenied("Synthetic setup evidence unavailable.") from None
