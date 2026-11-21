"""Persist a bounded test-only login attempt count without retaining usernames.

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


@transaction.atomic
def charge_login_attempt(*, username):
    """Return (allowed, retry_after_seconds) for a syntactically valid login.

    Both unknown and known usernames are charged. This is NOT an IP/network
    abuse control and does not authorize exposing the test-only login route.
    """
    digest = _identifier_digest(username)
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
