"""Read-only, session-authenticated family endpoints for test-only integration.

No registration, session issuance, household grants, or financial records
are exposed. These URLs are enabled only in disposable test settings.
"""

from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from .access import require_household_access
from .models import HouseholdStudent


def _authorized_or_error(request, school_id, household_id):
    try:
        return (
            require_household_access(
                request.user, school_id=school_id, household_id=household_id
            ),
            None,
        )
    except PermissionDenied:
        return None, JsonResponse({"detail": "Forbidden."}, status=403)
    except Http404:
        # Unknown, other school, revoked and unauthorized all look the same.
        return None, JsonResponse({"detail": "Not found."}, status=404)


@never_cache
@require_safe
def household_detail(request, school_id, household_id):
    household, error = _authorized_or_error(request, school_id, household_id)
    if error is not None:
        return error
    return JsonResponse({"id": str(household.pk), "name": household.name})


@never_cache
@require_safe
def household_students(request, school_id, household_id):
    household, error = _authorized_or_error(request, school_id, household_id)
    if error is not None:
        return error
    links = (
        HouseholdStudent.objects.for_school(school_id)
        .filter(household_id=household.pk)
        .select_related("student")
        .order_by("student_id")
    )
    return JsonResponse(
        {
            "household_id": str(household.pk),
            "students": [
                {
                    "id": str(link.student_id),
                    "first_name": link.student.first_name,
                    "last_name": link.student.last_name,
                }
                for link in links
            ],
        }
    )
