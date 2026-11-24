"""Disposable-test rehearsal of immutable setup intent persistence.

There is no runtime caller, URL, school creation, activation, job runner,
payment, or SIS integration. The separately reviewed candidate validator
and provisioning-specific MFA must be bound to a future authorized service.
A fingerprint supplied here is not proof that a real candidate was validated.
"""

import re
from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction

from .demo_platform_operations import _authorized_operator
from .models import SchoolSetupIntent


_TEST_SETTINGS = frozenset((
    "jireh.schools.test_settings",
    "jireh.schools.postgres_test_settings",
))


def record_synthetic_setup_intent(*, operator, idempotency_key, candidate_digest):
    """Persist exactly one fictional receipt; replay only its exact owner and payload.

    This service is disabled even in the ordinary localhost demo. The test
    suite must explicitly opt in using its disposable settings. Never use a
    caller-provided operator or fingerprint as proof of live authorization.
    """
    if (settings.SETTINGS_MODULE not in _TEST_SETTINGS
            or getattr(settings, "JIREH_SYNTHETIC_SETUP_INTENT_ONLY", False) is not True
            or not isinstance(operator, get_user_model())
            or not _authorized_operator(operator)):
        raise PermissionDenied("Synthetic setup preparation disabled or denied.")
    if not isinstance(idempotency_key, UUID) or not idempotency_key.int:
        raise ValidationError("Invalid setup request key.")
    if (type(candidate_digest) is not str
            or re.fullmatch(r"[0-9a-f]{64}", candidate_digest) is None):
        raise ValidationError("Invalid setup candidate fingerprint.")

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
