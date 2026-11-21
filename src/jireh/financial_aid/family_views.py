"""Session-authenticated create-or-resume of DRAFT-only family applications.

This route is included exclusively by disposable Django test settings. No
financial fields, attachments, consent, submission or payment are exposed.
"""

from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from jireh.schools.access import require_household_access
from jireh.schools.models import AcademicYear

from .models import AidApplication
from .services import get_or_create_annual_draft


@never_cache
@ensure_csrf_cookie
@csrf_protect
@require_http_methods(["GET", "POST"])
def family_annual_draft(request, school_id, household_id, academic_year_id):
    """GET an existing draft or POST to idempotently create one.

    The URL and school header are not authentication or authorization. The
    authenticated user's active household grant is authoritative, and the
    academic year must belong to that same school.
    """
    try:
        household = require_household_access(
            request.user, school_id=school_id, household_id=household_id
        )
        year = get_object_or_404(
            AcademicYear.objects.for_school(household.school_id),
            pk=academic_year_id,
        )
        if request.method == "POST":
            draft = get_or_create_annual_draft(
                user=request.user,
                school_id=household.school_id,
                household_id=household.pk,
                academic_year_id=year.pk,
            )
        else:
            draft = (
                AidApplication.objects.for_school(household.school_id)
                .filter(household_id=household.pk, academic_year_id=year.pk)
                .first()
            )
            if draft is None:
                raise Http404("Draft not found")
    except PermissionDenied:
        return JsonResponse({"detail": "Forbidden."}, status=403)
    except (Http404, AcademicYear.DoesNotExist):
        return JsonResponse({"detail": "Not found."}, status=404)

    return JsonResponse(
        {
            "id": str(draft.pk),
            "school_id": str(draft.school_id),
            "household_id": str(draft.household_id),
            "academic_year_id": str(draft.academic_year_id),
            "status": draft.status,
        }
    )
