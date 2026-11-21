"""Durable, account-wide attempt budget for test-only invitation redemption.

Uses the authoritative Django database, not a process-local cache. Locking the
authentication row serializes competing sessions and independent school URLs,
including before the budget row exists. Persist the debit before invoking the
redemption service, so rejected requests are counted and cannot roll back it.
"""

from datetime import timedelta
from math import ceil

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import RedemptionAttemptBudget


MAX_REDEMPTION_ATTEMPTS = 10
REDEMPTION_WINDOW = timedelta(minutes=15)


@transaction.atomic
def charge_redemption_attempt(*, user):
    """Return (allowed, retry_after_seconds) for an authenticated account.

    No invitation tokens, request IPs, school IDs, or household IDs are stored.
    Call before parsing submitted credentials; a failed/malformed attempt costs
    one debit. Authentication is checked by the caller, and checked again here
    under the database lock.
    """
    account = (
        get_user_model()._default_manager.select_for_update()
        .filter(pk=user.pk, is_active=True)
        .first()
    )
    if account is None:
        return False, 0

    now = timezone.now()
    budget, _ = RedemptionAttemptBudget.objects.get_or_create(
        user=account,
        defaults={"window_started_at": now, "attempt_count": 0},
    )
    deadline = budget.window_started_at + REDEMPTION_WINDOW
    if now >= deadline:
        budget.window_started_at = now
        budget.attempt_count = 0
        deadline = now + REDEMPTION_WINDOW

    if budget.attempt_count >= MAX_REDEMPTION_ATTEMPTS:
        return False, max(1, ceil((deadline - now).total_seconds()))

    budget.attempt_count += 1
    budget.save(
        update_fields=["window_started_at", "attempt_count", "updated_at"]
    )
    return True, 0
