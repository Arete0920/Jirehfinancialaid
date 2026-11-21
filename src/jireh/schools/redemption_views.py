"""Disposable test-only, authenticated household invitation redemption HTTP.

Do not include this module in jireh.runtime.urls: it has no customer-facing
login, rate limiting, identity onboarding or certified delivery transport.
"""

import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from .attempt_budget import charge_redemption_attempt
from .redemption import redeem_household_invitation


_MAX_BODY_BYTES = 512
_KEYS = frozenset(("invitation_token", "mailbox_token"))


def _parse_codes(request):
    # Reject oversize bodies before parsing; do not log raw secrets or payloads.
    length = request.META.get("CONTENT_LENGTH")
    if length:
        try:
            if int(length) > _MAX_BODY_BYTES:
                raise ValueError("oversize")
        except (TypeError, ValueError):
            raise ValidationError("Invalid redemption request.") from None

    if request.content_type != "application/json":
        raise ValidationError("Invalid redemption request.")
    raw = request.body
    if len(raw) > _MAX_BODY_BYTES:
        raise ValidationError("Invalid redemption request.")

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs)
    except (UnicodeError, ValueError, TypeError):
        raise ValidationError("Invalid redemption request.") from None

    if not isinstance(data, dict) or frozenset(data) != _KEYS:
        raise ValidationError("Invalid redemption request.")
    for value in data.values():
        if not isinstance(value, str) or len(value) != 64:
            raise ValidationError("Invalid redemption request.")
    return data


@never_cache
@ensure_csrf_cookie
@csrf_protect
@require_http_methods(["GET", "POST"])
def test_household_redemption(request, school_id, household_id):
    """GET CSRF bootstrap; POST consumes two secrets in a single transaction.

    Never returns either code or underlying existence/authorization details.
    """
    user = request.user
    if not getattr(user, "is_authenticated", False) or not getattr(
        user, "is_active", False
    ):
        return JsonResponse({"detail": "Forbidden."}, status=403)

    if request.method == "GET":
        return JsonResponse({"ready": True})

    # Debit every authenticated POST, including malformed or invalid codes.
    # Use a database-persisted, account-wide counter before credential lookup.
    allowed, retry_after = charge_redemption_attempt(user=user)
    if not allowed:
        if retry_after == 0:
            return JsonResponse({"detail": "Forbidden."}, status=403)
        response = JsonResponse(
            {"detail": "Too many redemption attempts."}, status=429,
        )
        response["Retry-After"] = str(retry_after)
        return response

    try:
        data = _parse_codes(request)
    except ValidationError:
        return JsonResponse({"detail": "Invalid request."}, status=400)

    try:
        grant = redeem_household_invitation(
            user=user,
            school_id=school_id,
            household_id=household_id,
            invitation_token=data["invitation_token"],
            mailbox_token=data["mailbox_token"],
        )
    except PermissionDenied:
        return JsonResponse({"detail": "Forbidden."}, status=403)
    except (Http404, ValidationError):
        # No information about target school, token, household or existing grant.
        return JsonResponse({"detail": "Not found."}, status=404)

    return JsonResponse(
        {"household_id": str(grant.household_id), "status": "redeemed"},
        status=200,
    )
