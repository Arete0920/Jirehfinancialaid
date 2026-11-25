"""Disposable school-director password + WebAuthn session acceptance.

No enrollment, recovery, hosted route or real identity provider. Password-stage
sessions are restricted to the assertion endpoints; only a fresh signed proof
for the active school grant establishes director readback access.
"""
import json
import os
import re
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied, RequestDataTooBig
from django.http import JsonResponse
from django.middleware.csrf import get_token, rotate_token
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_POST

from jireh.schools.director_webauthn import (
    _session_digest, begin_director_assertion, complete_director_assertion,
)
from jireh.schools.login_budget import charge_director_assertion_attempt
from jireh.schools.models import DirectorWebAuthnChallenge, DirectorWebAuthnCredential, GrantTransitionEvent
from jireh.schools.session_views import authenticate_session, end_session

DIRECTOR_SESSION_KEY = "jireh_customer_director_session"
_TEST_SETTINGS = frozenset({"jireh.schools.test_settings", "jireh.schools.postgres_test_settings"})
_PENDING_SECONDS = 300
_VERIFIED_SECONDS = 900
_MAX_ASSERTION_BYTES = 16384
_MAX_CREDENTIALS = 20
_DIGEST = re.compile(r"\A[0-9a-f]{64}\Z")


def disposable_identity_context():
    startup = os.environ.get("DJANGO_SETTINGS_MODULE")
    return startup in _TEST_SETTINGS and getattr(settings, "SETTINGS_MODULE", None) in (None, startup)


def director_session_available(request):
    rp = getattr(settings, "JIREH_DIRECTOR_WEBAUTHN_RP_ID", None)
    return (
        disposable_identity_context()
        and getattr(settings, "JIREH_CUSTOMER_DIRECTOR_SESSION_ACCEPTANCE", False) is True
        and getattr(settings, "JIREH_DIRECTOR_WEBAUTHN_ACCEPTANCE", False) is True
        and isinstance(rp, str) and request.is_secure() and request.get_host() == rp
    )


def _director_credentials(user, school_id):
    if (not user.is_authenticated or not user.is_active or user.is_staff or user.is_superuser
            or user.user_permissions.exists() or user.groups.exists()):
        return DirectorWebAuthnCredential.objects.none()
    return DirectorWebAuthnCredential.objects.filter(
        grant__school_id=school_id, grant__school__is_active=True, grant__user_id=user.pk,
        grant__is_active=True, grant__role="AID_DIRECTOR", revoked_at__isnull=True,
        enrollment_verified_at__isnull=False, enrollment_verified_at__lte=timezone.now(),
        rp_id=getattr(settings, "JIREH_DIRECTOR_WEBAUTHN_RP_ID", None),
    )


def _pending(request, school_id):
    marker = request.session.get(DIRECTOR_SESSION_KEY)
    if (not isinstance(marker, dict) or marker.get("stage") != "password"
            or marker.get("school") != str(school_id)
            or type(marker.get("expires")) is not int
            or marker["expires"] <= timezone.now().timestamp()
            or not _director_credentials(request.user, school_id).exists()):
        raise PermissionDenied("Director authentication required.")
    return marker


def director_session_authorized(request, school_id):
    """Recheck proof, exact school, expiry and credential/grant revocation."""
    if not director_session_available(request):
        return False
    marker = request.session.get(DIRECTOR_SESSION_KEY)
    if (not isinstance(marker, dict) or marker.get("stage") != "verified"
            or marker.get("school") != str(school_id)
            or marker.get("binding") != _session_digest(request.session.session_key)):
        return False
    try:
        proof_id = UUID(marker["proof"])
    except (ValueError, TypeError, KeyError, AttributeError):
        return False
    now = timezone.now()
    proof = DirectorWebAuthnChallenge.objects.filter(
        pk=proof_id, credential__in=_director_credentials(request.user, school_id),
        verified_at__gte=now - timedelta(seconds=_VERIFIED_SECONDS), verified_at__lte=now,
    ).select_related("credential__grant").first()
    if proof is None or proof.credential.grant.updated_at > proof.verified_at:
        return False
    # PostgreSQL also captures raw grant status changes, even if updated_at was
    # not touched. A revoke/reactivate must never restore a previous session.
    return not GrantTransitionEvent.objects.filter(
        grant_kind=GrantTransitionEvent.KIND_STAFF, grant_id=proof.credential.grant_id,
        created_at__gt=proof.verified_at,
    ).exists()


def _body(request, keys):
    if request.content_type != "application/json":
        raise ValueError("Invalid request.")
    try:
        length = int(request.META.get("CONTENT_LENGTH") or 0)
        if not 0 <= length <= _MAX_ASSERTION_BYTES:
            raise ValueError("Invalid request.")
        raw = request.body
        if len(raw) > _MAX_ASSERTION_BYTES:
            raise ValueError("Invalid request.")
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate key.")
                result[key] = value
            return result
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except (TypeError, ValueError, UnicodeError, RequestDataTooBig, RecursionError):
        raise ValueError("Invalid request.") from None
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("Invalid request.")
    return value


def _attempt(request):
    allowed, retry = charge_director_assertion_attempt(user_id=request.user.pk)
    if allowed:
        return None
    response = JsonResponse({"detail": "Too many verification attempts."}, status=429)
    response["Retry-After"] = str(retry)
    return response


@csrf_protect
@require_http_methods(["GET", "POST"])
def director_login(request, school_id):
    if request.method == "GET":
        return JsonResponse({"csrf_token": get_token(request)})
    response = authenticate_session(request, eligible=lambda user: _director_credentials(user, school_id).exists())
    if response.status_code != 200:
        return response
    credentials = list(_director_credentials(request.user, school_id).order_by("pk").values_list(
        "credential_id_digest", flat=True,
    )[:_MAX_CREDENTIALS + 1])
    if not credentials or len(credentials) > _MAX_CREDENTIALS:
        end_session(request)
        raise PermissionDenied("Director authentication unavailable.")
    request.session[DIRECTOR_SESSION_KEY] = {
        "stage": "password", "school": str(school_id),
        "expires": int(timezone.now().timestamp()) + _PENDING_SECONDS,
    }
    request.session.set_expiry(_PENDING_SECONDS)
    return JsonResponse({"authenticated": False, "verification_required": True,
                         "credential_refs": credentials, "csrf_token": get_token(request)})


@csrf_protect
@require_POST
def director_begin(request, school_id):
    _pending(request, school_id)
    limited = _attempt(request)
    if limited is not None:
        return limited
    try:
        value = _body(request, {"credential_id_digest"})
        digest = value["credential_id_digest"]
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            raise ValueError("Invalid request.")
    except ValueError:
        return JsonResponse({"detail": "Invalid request."}, status=400)
    options, challenge = begin_director_assertion(
        actor=request.user, school_id=school_id, session_key=request.session.session_key,
        credential_id_digest=digest,
    )
    return JsonResponse({"challenge_id": str(challenge), "options": dict(options)})


@csrf_protect
@require_POST
def director_complete(request, school_id):
    _pending(request, school_id)
    limited = _attempt(request)
    if limited is not None:
        return limited
    try:
        value = _body(request, {"challenge_id", "assertion"})
        challenge = UUID(value["challenge_id"])
        assertion = value["assertion"]
        if not isinstance(assertion, dict):
            raise ValueError("Invalid request.")
    except (ValueError, TypeError, AttributeError):
        return JsonResponse({"detail": "Invalid request."}, status=400)
    proof = complete_director_assertion(
        actor=request.user, school_id=school_id, session_key=request.session.session_key,
        challenge_id=challenge, response=assertion,
    )
    request.session.cycle_key()
    rotate_token(request)
    request.session[DIRECTOR_SESSION_KEY] = {
        "stage": "verified", "school": str(school_id), "proof": str(proof),
        "binding": _session_digest(request.session.session_key),
    }
    request.session.set_expiry(_VERIFIED_SECONDS)
    if not director_session_authorized(request, school_id):
        end_session(request)
        raise PermissionDenied("Director authentication unavailable.")
    return JsonResponse({"authenticated": True, "csrf_token": get_token(request)})


@csrf_protect
@require_POST
def director_logout(request, school_id):
    marker = request.session.get(DIRECTOR_SESSION_KEY)
    if not isinstance(marker, dict) or marker.get("school") != str(school_id):
        raise PermissionDenied("Director session unavailable.")
    return end_session(request)
