"""Persist bounded test sign-in and internal operator attempts without raw IDs.

HMAC-protects identifiers with Django's secret key and serializes attempts
against the same digest on PostgreSQL. A unique constraint arbitrates first
use, while an unavailable database must fail closed at the HTTP caller.
"""

import hashlib
import hmac
import unicodedata
from datetime import timedelta
from math import ceil

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import LoginAttemptBudget


MAX_LOGIN_ATTEMPTS = 10
LOGIN_ATTEMPT_WINDOW = timedelta(minutes=15)


def _identifier_digest(username):
    normalized = unicodedata.normalize("NFKC", username).casefold()
    message = ("jireh-login-attempt-v1:" + normalized).encode("utf-8")
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def _bootstrap_operator_digest(operator_id):
    # Distinct HMAC domain: a family username cannot alias this counter.
    message = ("jireh-bootstrap-operator-attempt-v1:" + str(operator_id)).encode("utf-8")
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), message, hashlib.sha256).hexdigest()


@transaction.atomic
def _charge_digest(digest):
    """Apply an HMAC-only, database-serialized attempt budget."""
    now = timezone.now()
    budget, _ = (
        LoginAttemptBudget.objects.select_for_update().get_or_create(
            identifier_digest=digest,
            defaults={"window_started_at": now, "attempt_count": 0},
        )
    )
    deadline = budget.window_started_at + LOGIN_ATTEMPT_WINDOW

    if now >= deadline:
        budget.window_started_at = now
        budget.attempt_count = 0
        deadline = now + LOGIN_ATTEMPT_WINDOW

    if budget.attempt_count >= MAX_LOGIN_ATTEMPTS:
        return False, max(1, ceil((deadline - now).total_seconds()))

    budget.attempt_count += 1
    budget.save(
        update_fields=["window_started_at", "attempt_count", "updated_at"]
    )
    return True, 0

def charge_login_attempt(*, username):
    """Return (allowed, retry_after_seconds) for test-only sign-in attempts."""
    return _charge_digest(_identifier_digest(username))


def charge_bootstrap_operator_attempt(*, operator_id):
    """Charge a distinct operator-scoped bootstrap attempt, never a username."""
    return _charge_digest(_bootstrap_operator_digest(operator_id))


def charge_director_assertion_attempt(*, user_id):
    """Bound both valid and invalid MFA requests across pending sessions."""
    message = ("jireh-director-assertion-attempt-v1:" + str(user_id)).encode("utf-8")
    digest = hmac.new(settings.SECRET_KEY.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return _charge_digest(digest)
