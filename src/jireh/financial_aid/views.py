"""Staff application inventory, enabled only in disposable test routing.

School identity is verified from an explicit aid-director grant. This is
read-only: no family finances, documents, award recommendations or mutations.
"""

from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from jireh.schools.access import require_aid_director_access
from jireh.schools.models import AcademicYear

from .models import AidApplication


@never_cache
@require_safe
def staff_application_index(request, school_id, academic_year_id):
    try:
        school = require_aid_director_access(
            request.user, school_id=school_id
        )
    except PermissionDenied:
        return JsonResponse({"detail": "Forbidden."}, status=403)
    except Http404:
        return JsonResponse({"detail": "Not found."}, status=404)

    year = get_object_or_404(
        AcademicYear.objects.for_school(school.pk),
        pk=academic_year_id,
    )
    # Cap responses to protect the read-only prototype from unbounded queries.
    # Pagination and full school reporting require a separate reviewed feature.
    rows = list(
        AidApplication.objects.for_school(school.pk)
        .filter(academic_year_id=year.pk)
        .order_by("created_at", "pk")
        .values("id", "household_id", "status")[:101]
    )
    return JsonResponse(
        {
            "school_id": str(school.pk),
            "academic_year_id": str(year.pk),
            "applications": [
                {
                    "id": str(row["id"]),
                    "household_id": str(row["household_id"]),
                    "status": row["status"],
                }
                for row in rows[:100]
            ],
            "has_more": len(rows) > 100,
        }
    )
