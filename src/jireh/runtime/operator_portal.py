"""MFA-bound operations portal for disposable registry and preparation evidence."""
import re
import secrets
from datetime import timedelta
from functools import wraps
from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.http import JsonResponse, HttpResponseNotFound
from django.middleware.csrf import get_token, rotate_token
from django.shortcuts import render
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from jireh.schools.login_budget import charge_bootstrap_operator_attempt
from jireh.schools.models import OperatorWebAuthnChallenge, OperatorWebAuthnCredential
from jireh.schools.operator_webauthn_registry import (
    begin_registered_operator_challenge, complete_registered_operator_challenge,
)
from jireh.schools.session_views import authenticate_session, end_session
from jireh.schools.synthetic_school_registry import (
    RegistryIntegrityError, read_synthetic_preparation_counts, read_synthetic_school_registry,
)
from .customer_director_sessions import _body, DIRECTOR_SESSION_KEY
from .customer_family_sessions import FAMILY_SESSION_KEY
from .customer_onboarding import ONBOARDING_SESSION_KEY
from .operator_portal_policy import configured_preparation_candidate, operations_profile_available

SESSION_KEY = "jireh_operations_acceptance"
_PENDING = 300
_VERIFIED = 900
_DIGEST = re.compile(r"\A[0-9a-f]{64}\Z")
_OTHER_SESSIONS = (FAMILY_SESSION_KEY, DIRECTOR_SESSION_KEY, ONBOARDING_SESSION_KEY)


def _binding(request):
    key = request.session.session_key
    if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9]{32}", key):
        raise PermissionDenied("Operations session unavailable.")
    return salted_hmac("jireh-operations-session-v1", key, algorithm="sha256").hexdigest()


def _credentials(user):
    allowlist = getattr(settings, "JIREH_BOOTSTRAP_OPERATOR_IDS", ())
    if (not isinstance(allowlist, (tuple, frozenset)) or len(allowlist) < 2
            or len(set(allowlist)) != len(allowlist)
            or not user.is_authenticated or not user.is_active or not user.is_staff
            or not user.is_superuser or user.pk not in allowlist):
        return OperatorWebAuthnCredential.objects.none()
    rp = getattr(settings, "JIREH_OPERATOR_PORTAL_RP_ID", None)
    return OperatorWebAuthnCredential.objects.filter(
        operator_id=user.pk, rp_id=rp, origin=f"https://{rp}", revoked_at__isnull=True,
        enrollment_verified_at__isnull=False, enrollment_verified_at__lte=timezone.now(),
    )


def _available(request):
    rp = getattr(settings, "JIREH_OPERATOR_PORTAL_RP_ID", None)
    return (operations_profile_available() and isinstance(rp, str) and bool(rp)
            and request.is_secure() and request.get_host() == rp)


def operations_only(view):
    @never_cache
    @wraps(view)
    def guarded(request, *args, **kwargs):
        if not _available(request):
            response = HttpResponseNotFound()
        else:
            try:
                if any(key in request.session for key in _OTHER_SESSIONS):
                    raise PermissionDenied("Separate operator session required.")
                response = view(request, *args, **kwargs)
            except PermissionDenied:
                response = JsonResponse({"detail": "Forbidden."}, status=403)
            except (DatabaseError, RegistryIntegrityError):
                response = JsonResponse({"detail": "Operations evidence unavailable."}, status=503)
        response["X-Content-Type-Options"] = "nosniff"
        response["X-Frame-Options"] = "DENY"
        response["Referrer-Policy"] = "no-referrer"
        response["X-Robots-Tag"] = "noindex, nofollow"
        return response
    return guarded


def _pending(request):
    marker = request.session.get(SESSION_KEY)
    if (not isinstance(marker, dict) or marker.get("stage") != "password"
            or marker.get("binding") != _binding(request)
            or type(marker.get("expires")) is not int
            or marker["expires"] <= timezone.now().timestamp()
            or not _credentials(request.user).exists()):
        raise PermissionDenied("Operator authentication required.")
    return marker


def operator_authorized(request):
    if not _available(request) or any(key in request.session for key in _OTHER_SESSIONS):
        return False
    marker = request.session.get(SESSION_KEY)
    if not isinstance(marker, dict) or marker.get("stage") != "verified":
        return False
    try:
        if marker.get("binding") != _binding(request):
            return False
        proof_id = UUID(marker["proof"])
    except (PermissionDenied, KeyError, TypeError, ValueError, AttributeError):
        return False
    now = timezone.now()
    proof = OperatorWebAuthnChallenge.objects.filter(
        pk=proof_id, operator_id=request.user.pk, closed_at__isnull=False,
        verified_at__gte=now-timedelta(seconds=_VERIFIED), verified_at__lte=now,
        rp_id=settings.JIREH_OPERATOR_PORTAL_RP_ID,
        origin=f"https://{settings.JIREH_OPERATOR_PORTAL_RP_ID}",
    ).first()
    return bool(proof and _credentials(request.user).filter(
        credential_id_digest=proof.credential_id_digest,
        enrollment_verified_at__lte=proof.verified_at,
    ).exists())


def _limited(request):
    allowed, retry = charge_bootstrap_operator_attempt(operator_id=request.user.pk)
    if allowed:
        return None
    response = JsonResponse({"detail": "Too many verification attempts."}, status=429)
    response["Retry-After"] = str(retry)
    return response


@csrf_protect
@require_http_methods(["GET", "POST"])
def operator_login(request):
    if request.method == "GET":
        return JsonResponse({"csrf_token": get_token(request)})
    response = authenticate_session(request, eligible=lambda user: _credentials(user).exists())
    if response.status_code != 200:
        return response
    refs = list(_credentials(request.user).order_by("pk").values_list("credential_id_digest", flat=True)[:21])
    if not 0 < len(refs) <= 20:
        end_session(request)
        raise PermissionDenied("Operator authentication unavailable.")
    request.session[SESSION_KEY] = {"stage": "password", "binding": _binding(request),
                                    "expires": int(timezone.now().timestamp()) + _PENDING}
    request.session.set_expiry(_PENDING)
    return JsonResponse({"authenticated": False, "verification_required": True,
                         "credential_refs": refs, "csrf_token": get_token(request)})


@csrf_protect
@require_POST
def operator_begin(request):
    marker = _pending(request)
    limited = _limited(request)
    if limited is not None:
        return limited
    try:
        digest = _body(request, {"credential_id_digest"})["credential_id_digest"]
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            raise ValueError()
    except ValueError:
        return JsonResponse({"detail": "Invalid request."}, status=400)
    if not _credentials(request.user).filter(credential_id_digest=digest).exists():
        raise PermissionDenied("Operator credential unavailable.")
    options, proof = begin_registered_operator_challenge(operator=request.user, credential_id_digest=digest)
    # The client cannot choose which durable challenge it completes. Only the
    # challenge issued to this server-side password session is accepted.
    request.session[SESSION_KEY] = {**marker, "challenge": str(proof)}
    return JsonResponse({"options": dict(options)})


@csrf_protect
@require_POST
def operator_complete(request):
    marker = _pending(request)
    limited = _limited(request)
    if limited is not None:
        return limited
    try:
        challenge_id = UUID(marker["challenge"])
    except (KeyError, ValueError, TypeError, AttributeError):
        raise PermissionDenied("No session challenge.") from None
    try:
        assertion = _body(request, {"assertion"})["assertion"]
        if not isinstance(assertion, dict):
            raise ValueError()
    except ValueError:
        return JsonResponse({"detail": "Invalid request."}, status=400)
    complete_registered_operator_challenge(operator=request.user, challenge_id=challenge_id, response=assertion)
    request.session.cycle_key()
    rotate_token(request)
    request.session[SESSION_KEY] = {"stage": "verified", "proof": str(challenge_id), "binding": _binding(request)}
    request.session.set_expiry(_VERIFIED)
    if not operator_authorized(request):
        end_session(request)
        raise PermissionDenied("Operator authentication unavailable.")
    return JsonResponse({"authenticated": True, "csrf_token": get_token(request)})


@csrf_protect
@require_POST
def operator_logout(request):
    if not request.user.is_authenticated:
        raise PermissionDenied()
    return end_session(request)


@ensure_csrf_cookie
@require_safe
def operator_home(request):
    if request.GET:
        return JsonResponse({"detail": "Query parameters are not accepted."}, status=400)
    nonce = secrets.token_urlsafe(24)
    context = {"csp_nonce": nonce, "authenticated": request.user.is_authenticated}
    if operator_authorized(request):
        context["schools"] = read_synthetic_school_registry(operator=request.user)
        context["preparation_counts"] = read_synthetic_preparation_counts(operator=request.user)
        context["preparation_total"] = sum(context["preparation_counts"].values())
        # Recheck after both readbacks, including a concurrent credential revoke.
        if not operator_authorized(request):
            raise PermissionDenied()
        context["preparation_enabled"] = configured_preparation_candidate(request) is not None
        context["verified"] = True
    elif request.user.is_authenticated:
        try:
            _pending(request)
        except PermissionDenied:
            pass
        else:
            refs = list(_credentials(request.user).order_by("pk").values_list("credential_id_digest", flat=True)[:21])
            if 0 < len(refs) <= 20:
                context["credential_refs"] = refs
    response = render(request, "jireh/operator_portal.html", context)
    response["Content-Security-Policy"] = (
        f"default-src 'none'; style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; "
        "connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    )
    return response
