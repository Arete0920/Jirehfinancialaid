"""Disposable test-only Django session login and logout.

No registration, password-reset delivery, account recovery, public routes or
deployment changes. The login POST requires CSRF and rejects unknown accounts
with the same response as incorrect passwords. Database admission control
persists across sessions and accounts for invalid and valid submissions.
"""

import json

from django.contrib.auth import authenticate, login, logout
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST

from .login_budget import charge_login_attempt


MAX_LOGIN_JSON_BYTES = 2048
LOGIN_SESSION_LIFETIME_SECONDS = 900


def _parse_login_credentials(request):
    if request.content_type != "application/json":
        raise ValidationError("Invalid sign-in request.")
    length = request.META.get("CONTENT_LENGTH")
    if length:
        try:
            if int(length) > MAX_LOGIN_JSON_BYTES:
                raise ValueError("oversize")
        except (ValueError, TypeError):
            raise ValidationError("Invalid sign-in request.") from None
    body = request.body
    if len(body) > MAX_LOGIN_JSON_BYTES:
        raise ValidationError("Invalid sign-in request.")

    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate login JSON key.")
            result[key] = value
        return result

    try:
        values = json.loads(
            body.decode("utf-8"), object_pairs_hook=reject_duplicates
        )
    except (UnicodeError, ValueError, TypeError):
        raise ValidationError("Invalid sign-in request.") from None

    if not isinstance(values, dict) or set(values) != {"username", "password"}:
        raise ValidationError("Invalid sign-in request.")

    username, password = values["username"], values["password"]
    if (
        not isinstance(username, str)
        or not 1 <= len(username) <= 150
        or not isinstance(password, str)
        or not 1 <= len(password) <= 1024
    ):
        raise ValidationError("Invalid sign-in request.")
    return username, password


@never_cache
@ensure_csrf_cookie
@csrf_protect
@require_http_methods(["GET", "POST"])
def test_family_login(request):
    """GET creates CSRF cookie; POST authenticates and rotates session key."""
    if request.method == "GET":
        return JsonResponse({"ready": True})

    if getattr(request.user, "is_authenticated", False):
        return JsonResponse({"detail": "Forbidden."}, status=403)

    try:
        username, password = _parse_login_credentials(request)
    except ValidationError:
        return JsonResponse({"detail": "Invalid request."}, status=400)

    try:
        allowed, retry_after = charge_login_attempt(username=username)
    except DatabaseError:
        # Never attempt password authentication when the throttle is down.
        return JsonResponse({"detail": "Service unavailable."}, status=503)

    if not allowed:
        response = JsonResponse(
            {"detail": "Too many sign-in attempts."}, status=429,
        )
        response["Retry-After"] = str(retry_after)
        return response

    user = authenticate(request=request, username=username, password=password)
    if user is None or not getattr(user, "is_active", False):
        # No username, password, or reason for authentication failure is sent.
        return JsonResponse({"detail": "Invalid credentials."}, status=401)

    login(request, user)
    # The browser cookie and server-side session both expire within 15 minutes.
    request.session.set_expiry(LOGIN_SESSION_LIFETIME_SECONDS)
    return JsonResponse({"authenticated": True})


@never_cache
@csrf_protect
@require_POST
def test_family_logout(request):
    """Invalidate only the caller's session, including its prior session key."""
    logout(request)
    return JsonResponse({"authenticated": False})
