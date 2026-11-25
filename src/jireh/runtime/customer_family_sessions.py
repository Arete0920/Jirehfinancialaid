"""Separately gated family password-session acceptance; no identity enrollment.

Only existing active household grants are eligible. Privileged and mixed-role
accounts are denied. This does not certify mailbox ownership, identity proofing,
MFA, password recovery or production admission policy. Never mount live yet.
"""
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_POST

from jireh.schools.models import HouseholdAccess, SchoolStaffAccess
from jireh.schools.session_views import authenticate_session, end_session

FAMILY_SESSION_KEY = "jireh_customer_family_session"


def nonprivileged_family_account(user):
    """Conservative candidate policy; no privilege inferred from identity."""
    return (
        user.is_active and not user.is_staff and not user.is_superuser
        and not user.user_permissions.exists() and not user.groups.exists()
        and not SchoolStaffAccess.objects.filter(user_id=user.pk, is_active=True).exists()
    )


def family_session_eligible(user):
    return (
        nonprivileged_family_account(user)
        and HouseholdAccess.objects.filter(
            user_id=user.pk, is_active=True, household__is_active=True,
            household__school__is_active=True,
        ).exists()
    )


@csrf_protect
@require_http_methods(["GET", "POST"])
def family_login(request):
    """Deliver a masked CSRF token even before authentication."""
    if request.method == "GET":
        return JsonResponse({"csrf_token": get_token(request)})
    return authenticate_session(request, eligible=family_session_eligible,
                                family_session_key=FAMILY_SESSION_KEY)


@csrf_protect
@require_POST
def family_logout(request):
    """Invalidate a family session even if its grant has since been revoked."""
    if request.session.get(FAMILY_SESSION_KEY) is not True:
        return JsonResponse({"detail": "Forbidden."}, status=403)
    return end_session(request)
