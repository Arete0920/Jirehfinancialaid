"""Test-only family student selection endpoints.

GET lists selected student IDs in the authenticated household's annual draft.
POST adds one pre-linked child to that same draft, idempotently. No read or
write in this module grants household access or changes tuition or payment.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .services import select_student_for_draft, selected_student_ids_for_draft


@never_cache
@ensure_csrf_cookie
@require_GET
def selected_students(request, school_id, household_id, academic_year_id):
    try:
        draft, ids = selected_student_ids_for_draft(
            user=request.user,
            school_id=school_id,
            household_id=household_id,
            academic_year_id=academic_year_id,
        )
    except PermissionDenied:
        return JsonResponse({"detail": "Forbidden."}, status=403)
    except Http404:
        return JsonResponse({"detail": "Not found."}, status=404)
    return JsonResponse(
        {
            "application_id": str(draft.pk),
            "student_ids": [str(student_id) for student_id in ids],
        }
    )


@never_cache
@csrf_protect
@require_POST
def select_student(request, school_id, household_id, academic_year_id, student_id):
    try:
        selection = select_student_for_draft(
            user=request.user,
            school_id=school_id,
            household_id=household_id,
            academic_year_id=academic_year_id,
            student_id=student_id,
        )
    except PermissionDenied:
        return JsonResponse({"detail": "Forbidden."}, status=403)
    except Http404:
        return JsonResponse({"detail": "Not found."}, status=404)
    except ValidationError:
        return JsonResponse({"detail": "Student selection unavailable."}, status=409)
    return JsonResponse(
        {
            "application_id": str(selection.application_id),
            "selection_id": str(selection.pk),
            "student_id": str(selection.household_student.student_id),
        }
    )
