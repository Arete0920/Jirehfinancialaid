"""Disposable-test rehearsal of immutable setup intent persistence.

There is no runtime caller, URL, school creation, activation, job runner,
payment, or SIS integration. This rehearsal binds the standalone proposal
validator to a server-generated, versioned fingerprint. Provisioning-specific
MFA, canonical timezone policy and live authorization remain separate.
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
from .school_setup_preflight import (
    SchoolSetupPreflightError,
    validate_school_setup_candidate,
)


_TEST_SETTINGS = frozenset((
    "jireh.schools.test_settings",
    "jireh.schools.postgres_test_settings",
))


def _candidate_evidence(payload):
    """Validate the proposal and derive its immutable V1 request identity."""
    try:
        candidate = validate_school_setup_candidate(payload)
    except SchoolSetupPreflightError:
        raise ValidationError("Invalid school setup proposal.") from None

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


def record_synthetic_setup_intent(*, operator, payload):
    """Persist one validated fictional receipt; allow only exact owned replay.

    This service is disabled even in the ordinary localhost demo. The test
    suite must explicitly opt in using its disposable settings. No caller
    fingerprint or prevalidated object is accepted as provisioning authority.
    """
    # Django's override_settings wraps Settings in UserSettingsHolder,
    # where SETTINGS_MODULE is None. Require the actual startup module
    # and reject any conflicting explicit settings-module override.
    startup_module = os.environ.get("DJANGO_SETTINGS_MODULE")
    configured_module = settings.SETTINGS_MODULE
    if (startup_module not in _TEST_SETTINGS
            or configured_module not in (None, startup_module)
            or getattr(settings, "JIREH_SYNTHETIC_SETUP_INTENT_ONLY", False) is not True
            or not isinstance(operator, get_user_model())
            or not _authorized_operator(operator)):
        raise PermissionDenied("Synthetic setup preparation disabled or denied.")
    idempotency_key, candidate_digest = _candidate_evidence(payload)

    try:
        with transaction.atomic(durable=True):
            # Serialize the fixture operator's claims and recheck persisted
            # authority, not only a potentially stale request.user instance.
            account = get_user_model()._default_manager.select_for_update().filter(
                pk=operator.pk,
            ).first()
            if account is None or not _authorized_operator(account):
                raise PermissionDenied("Synthetic setup preparation denied.")
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
