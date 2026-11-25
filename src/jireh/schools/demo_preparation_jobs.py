"""Disposable preparation-job rehearsal, never school creation or activation.

A queued receipt is checked for a conflicting school code. A successful
preflight is evidence of availability at that instant, not a reservation,
provisioned school, external authorization, or integration. The receipt
row serializes a bounded append-only event stream. No worker is launched.
"""

from dataclasses import asdict
from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction

from .demo_setup_intents import (
    _candidate_evidence, _locked_setup_operator, _require_setup_context,
)
from .models import School, SchoolPreparationEvent, SchoolSetupIntent
from .school_setup_preflight import (
    SchoolSetupPreflightError,
    validate_school_setup_candidate,
)


_MAX_ATTEMPTS = 3  # Initial attempt plus two explicit, test-only retries.
_COMMANDS = {"QUEUE": "QUEUED", "RUN": "STARTED", "RETRY": "REQUEUED"}
_REASONS = {
    "QUEUED": "", "STARTED": "", "PREPARED": "",
    "FAILED": "SCHOOL_CODE_CONFLICT",
    "REQUEUED": "CODE_CONFLICT_RECHECK",
}


def _check_context(operator, *, privileged=False):
    _require_setup_context(operator, privileged=privileged)
    if getattr(settings, "JIREH_SYNTHETIC_PREPARATION_JOB_ONLY", False) is not True:
        raise PermissionDenied("Synthetic preparation job disabled or denied.")


def _valid_transition(previous, event, seen):
    """Only a run's STARTED and outcome may share a request key."""
    if previous is None:
        return (event.action == "QUEUED" and event.attempt == 1
                and event.request_key not in seen)
    if previous.action in ("QUEUED", "REQUEUED"):
        return (event.action == "STARTED" and event.attempt == previous.attempt
                and event.request_key not in seen)
    if previous.action == "STARTED":
        return (event.action in ("PREPARED", "FAILED")
                and event.attempt == previous.attempt
                and event.request_key == previous.request_key)
    if previous.action == "FAILED":
        return (event.action == "REQUEUED" and event.attempt == previous.attempt + 1
                and event.request_key not in seen)
    return False


def _verified_history(intent):
    history = list(intent.preparation_events.order_by("sequence"))
    previous = None
    seen = set()
    for sequence, event in enumerate(history, start=1):
        if (event.sequence != sequence or sequence > 9
                or event.actor_id != intent.proposed_by_id
                or not event.request_key.int
                or not 1 <= event.attempt <= _MAX_ATTEMPTS
                or event.action not in _REASONS
                or event.reason != _REASONS[event.action]
                or not _valid_transition(previous, event, seen)):
            raise PermissionDenied("Preparation history is inconsistent.")
        seen.add(event.request_key)
        previous = event
    if previous is not None and previous.action == "STARTED":
        # A run always commits both events or neither; never resume a
        # partially recorded run or invent its outcome.
        raise PermissionDenied("Preparation history is incomplete.")
    return history


def _append(intent, actor, history, request_key, action, attempt):
    event = SchoolPreparationEvent.objects.create(
        intent=intent, actor=actor, request_key=request_key,
        sequence=len(history) + 1, attempt=attempt, action=action,
        reason=_REASONS[action],
    )
    history.append(event)
    return event


def _apply_command(intent, actor, candidate, history, command, request_key):
    matches = [event for event in history if event.request_key == request_key]
    if matches:
        if matches[0].action != _COMMANDS[command]:
            raise PermissionDenied("Preparation request replay denied.")
        return matches[-1]  # Original command result, not a new transition.

    if command == "QUEUE":
        if history:
            raise ValidationError("Preparation already queued.")
        return _append(intent, actor, history, request_key, "QUEUED", 1)

    if not history:
        raise ValidationError("Preparation must first be queued.")
    last = history[-1]
    if command == "RETRY":
        if (last.action != "FAILED" or last.attempt >= _MAX_ATTEMPTS
                or School.objects.filter(code=candidate.code).exists()):
            raise ValidationError("Preparation retry denied.")
        return _append(
            intent, actor, history, request_key, "REQUEUED", last.attempt + 1,
        )

    if last.action not in ("QUEUED", "REQUEUED"):
        raise ValidationError("Only queued preparation may run.")
    _append(intent, actor, history, request_key, "STARTED", last.attempt)
    conflict = School.objects.filter(code=candidate.code).exists()
    return _append(
        intent, actor, history, request_key,
        "FAILED" if conflict else "PREPARED", last.attempt,
    )


def advance_synthetic_preparation(
    *, operator, payload, command, request_key, privileged=False,
):
    """Apply one explicit test command to the exact owned setup receipt.

    An identical request returns its original event without mutation.
    Retries are separate requests, require a recorded failure and a cleared
    code conflict, and cannot exceed two. PREPARED does not reserve a code.
    The ordinary demo operator remains distinct from the explicitly enabled
    privileged provisioning rehearsal in disposable tests.
    """
    _check_context(operator, privileged=privileged)
    if type(command) is not str or command not in _COMMANDS:
        raise ValidationError("Invalid preparation command.")
    if not isinstance(request_key, UUID) or not request_key.int:
        raise ValidationError("Invalid preparation request key.")
    try:
        candidate = validate_school_setup_candidate(payload)
    except SchoolSetupPreflightError:
        raise ValidationError("Invalid school setup proposal.") from None
    key, digest = _candidate_evidence(asdict(candidate), privileged=privileged)

    try:
        with transaction.atomic(durable=True):
            actor = _locked_setup_operator(operator, privileged=privileged)
            intent = SchoolSetupIntent.objects.select_for_update().filter(
                idempotency_key=key,
            ).first()
            if (intent is None or intent.proposed_by_id != actor.pk
                    or intent.candidate_digest != digest):
                raise PermissionDenied("Preparation receipt denied.")
            history = _verified_history(intent)
            return _apply_command(
                intent, actor, candidate, history, command, request_key,
            )
    except DatabaseError:
        raise PermissionDenied("Synthetic preparation evidence unavailable.") from None
