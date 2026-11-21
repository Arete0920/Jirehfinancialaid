"""Fail-closed authorization for a single school-specific household.

Identity is a Django-authenticated user. Household access is granted
explicitly to that user, never inferred from an email, shared student,
school header, staff flag, or another household relationship.
"""

from django.core.exceptions import PermissionDenied
from django.http import Http404

from .models import Household, School, SchoolStaffAccess


def require_household_access(user, *, school_id, household_id):
    """Return an authorized active household or deny without revealing tenancy."""
    if not getattr(user, "is_authenticated", False) or not getattr(
        user, "is_active", False
    ):
        raise PermissionDenied("Authentication required.")

    if not school_id or not household_id:
        raise Http404("Household not found.")

    household = (
        Household.objects.for_school(school_id)
        .filter(
            pk=household_id,
            school__is_active=True,
            is_active=True,
            access_grants__user_id=user.pk,
            access_grants__is_active=True,
        )
        .first()
    )
    if household is None:
        raise Http404("Household not found.")
    return household


def require_aid_director_access(user, *, school_id):
    """Authorize only an active, explicitly assigned school aid director.

    School ID is untrusted request scope, never proof of school authority.
    Do not infer permission from superuser, email, school membership or headers.
    """
    if not getattr(user, "is_authenticated", False) or not getattr(
        user, "is_active", False
    ):
        raise PermissionDenied("Authentication required.")
    if not school_id:
        raise Http404("School not found.")

    school = (
        School.objects.filter(
            pk=school_id,
            is_active=True,
            staff_access_grants__user_id=user.pk,
            staff_access_grants__is_active=True,
            staff_access_grants__role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        )
        .first()
    )
    if school is None:
        raise Http404("School not found.")
    return school
