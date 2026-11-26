"""Exact, opt-in fictional setup and preparation adapter; no school creation."""
from dataclasses import asdict
from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpResponseNotFound, JsonResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from jireh.schools.demo_preparation_jobs import _verified_history, advance_synthetic_preparation
from jireh.schools.demo_setup_intents import (
    _candidate_evidence, _locked_setup_operator, record_synthetic_setup_intent,
)
from jireh.schools.models import SchoolSetupIntent
from jireh.schools.school_setup_preflight import SchoolSetupCandidate
from jireh.schools.synthetic_school_registry import RegistryIntegrityError
from .customer_director_sessions import _body
from .operator_portal import operator_authorized
from .operator_portal_policy import operations_profile_available


def _fixture_payload(request):
    fixture = getattr(settings, "JIREH_OPERATOR_PREPARATION_FIXTURE", None)
    if (
        getattr(settings, "JIREH_OPERATOR_PREPARATION_ACCEPTANCE", False) is not True
        or not operations_profile_available()
        or not operator_authorized(request)
        or type(fixture) is not tuple or len(fixture) != 2
        or type(fixture[0]) is not int or fixture[0] != request.user.pk
        or type(fixture[1]) is not SchoolSetupCandidate
    ):
        raise PermissionDenied("Fictional preparation unavailable.")
    payload = asdict(fixture[1])
    try:
        _candidate_evidence(payload, privileged=True)
    except ValidationError:
        raise PermissionDenied("Fictional preparation unavailable.") from None
    return payload


def require_preparation_request(request, *, operator, payload):
    """The two existing write services recheck the session under their actor lock."""
    if (request.method != "POST" or operator.pk != request.user.pk
            or payload != _fixture_payload(request)):
        raise PermissionDenied("Fictional preparation denied.")


def _read_current(request, payload):
    key, digest = _candidate_evidence(payload, privileged=True)
    with transaction.atomic(durable=True):
        operator = _locked_setup_operator(request.user, privileged=True)
        if _fixture_payload(request) != payload:
            raise PermissionDenied("Fictional preparation denied.")
        receipt = SchoolSetupIntent.objects.filter(idempotency_key=key).first()
        if receipt is not None and (receipt.proposed_by_id != operator.pk or receipt.candidate_digest != digest):
            raise PermissionDenied("Fictional preparation denied.")
        try:
            history = _verified_history(receipt) if receipt else []
        except PermissionDenied:
            raise RegistryIntegrityError("Preparation evidence unavailable.") from None
        state = history[-1].action if history else ("RECEIVED" if receipt else "NOT_RECORDED")
        attempt = history[-1].attempt if history else 0
        return JsonResponse({
            "candidate": {field: payload[field] for field in ("code", "name", "timezone")},
            "state": state, "attempt": attempt,
        })


def _request_key(value):
    if type(value) is not str:
        raise ValueError("Invalid request key.")
    key = UUID(value)
    if not key.int or str(key) != value:
        raise ValueError("Invalid request key.")
    return key


@csrf_protect
@require_http_methods(["GET", "POST"])
def operator_preparation(request):
    if getattr(settings, "JIREH_OPERATOR_PREPARATION_ACCEPTANCE", False) is not True:
        return HttpResponseNotFound()
    payload = _fixture_payload(request)
    if request.GET:
        return JsonResponse({"detail": "Query parameters are not accepted."}, status=400)
    if request.method == "GET":
        return _read_current(request, payload)
    try:
        command = _body(request, {"command", "request_key"})
        action = command["command"]
        if action == "RECORD" and command["request_key"] is None:
            record_synthetic_setup_intent(
                operator=request.user, payload=payload, privileged=True, portal_request=request,
            )
            return JsonResponse({"recorded": True})
        if type(action) is not str or action not in ("QUEUE", "RUN", "RETRY"):
            raise ValueError("Invalid command.")
        event = advance_synthetic_preparation(
            operator=request.user, payload=payload, command=action,
            request_key=_request_key(command["request_key"]), privileged=True, portal_request=request,
        )
        # A replay returns the original command result, not current state.
        return JsonResponse({"event": event.action, "attempt": event.attempt})
    except (ValueError, ValidationError):
        return JsonResponse({"detail": "Invalid or unavailable preparation command."}, status=400)
