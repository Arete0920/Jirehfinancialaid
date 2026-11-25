"""Restricted first-household invitation acceptance; never live account creation.

The account must already have been provisioned by a separately accepted identity
process. Independently delivered invitation and mailbox proofs are mandatory.
No token issuance, delivery, recovery or production mounting occurs here.
"""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_POST

from jireh.schools.models import HouseholdAccess, School
from jireh.schools.redemption import redeem_household_invitation
from jireh.schools.redemption_views import redeem_authenticated_invitation
from jireh.schools.session_views import authenticate_session, end_session
from .customer_family_sessions import nonprivileged_family_account

ONBOARDING_SESSION_KEY = "jireh_customer_invitation_only_session"


def first_household_eligible(user):
    """First invitation only; no reactivation of historical household grants."""
    return (
        nonprivileged_family_account(user)
        and not HouseholdAccess.objects.filter(user_id=user.pk).exists()
    )


@csrf_protect
@require_http_methods(["GET", "POST"])
def onboarding_login(request):
    if request.method == "GET":
        return JsonResponse({"csrf_token": get_token(request)})
    response = authenticate_session(request, eligible=first_household_eligible,
                                    family_session_key=ONBOARDING_SESSION_KEY)
    if response.status_code == 200:
        return JsonResponse({"authenticated": True, "invitation_only": True})
    return response


def _invitation_session(request):
    return (
        getattr(request.user, "is_authenticated", False)
        and request.session.get(ONBOARDING_SESSION_KEY) is True
    )


@transaction.atomic
def _redeem_first_household(*, user, school_id, household_id, invitation_token, mailbox_token):
    # Keep the school-first grant-service lock order and serialize first-grant
    # decisions across schools on the account. The attempt debit has already
    # committed outside this transaction. Recheck eligibility under the lock.
    school = School.objects.select_for_update().filter(pk=school_id, is_active=True).first()
    if school is None:
        raise Http404("Invitation not found.")
    account = get_user_model()._default_manager.select_for_update().filter(pk=user.pk).first()
    if account is None or not first_household_eligible(account):
        raise PermissionDenied("Invitation-only session unavailable.")
    return redeem_household_invitation(
        user=account, school_id=school.pk, household_id=household_id,
        invitation_token=invitation_token, mailbox_token=mailbox_token,
    )


@csrf_protect
@require_POST
def onboarding_redeem(request, school_id, household_id):
    if not _invitation_session(request) or not first_household_eligible(request.user):
        return JsonResponse({"detail": "Forbidden."}, status=403)
    response = redeem_authenticated_invitation(
        request, school_id, household_id, redeem=_redeem_first_household,
    )
    if response.status_code != 200:
        return response
    # Never promote the restricted session. After the durable grant succeeds,
    # a fresh ordinary family sign-in must re-evaluate the current account.
    end_session(request)
    return JsonResponse({"status": "redeemed", "reauthentication_required": True})


@csrf_protect
@require_POST
def onboarding_logout(request):
    if not _invitation_session(request):
        return JsonResponse({"detail": "Forbidden."}, status=403)
    return end_session(request)
