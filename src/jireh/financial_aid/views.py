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

from .models import AidApplication, AidApplicationStudent


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


@never_cache
@require_safe
def staff_application_detail(request, school_id, academic_year_id, application_id):
    """Authorized read-only draft case detail for disposable test routing only.

    This deliberately excludes household identity, financial questions,
    assessments, documents, and awards. The URL is untrusted school scope.
    """
    try:
        school = require_aid_director_access(request.user, school_id=school_id)
    except PermissionDenied:
        return JsonResponse({"detail": "Forbidden."}, status=403)
    except Http404:
        return JsonResponse({"detail": "Not found."}, status=404)

    application = (
        AidApplication.objects.for_school(school.pk)
        .filter(
            pk=application_id,
            academic_year_id=academic_year_id,
            status=AidApplication.STATUS_DRAFT,
        )
        .first()
    )
    if application is None:
        return JsonResponse({"detail": "Not found."}, status=404)

    selected_ids = list(
        AidApplicationStudent.objects.for_school(school.pk)
        .filter(application_id=application.pk)
        .order_by("household_student__student_id")
        .values_list("household_student__student_id", flat=True)
    )
    return JsonResponse(
        {
            "school_id": str(school.pk),
            "academic_year_id": str(application.academic_year_id),
            "application_id": str(application.pk),
            "status": application.status,
            "selected_student_count": len(selected_ids),
            "selected_student_ids": [str(student_id) for student_id in selected_ids],
        }
    )


@never_cache
@require_safe
def staff_draft_workload(request, school_id, academic_year_id):
    """Synthetic-only, read-only counts for a grant-authorized school director.

    Never report draft counts as submitted applications or real awards.
    This view is routed only through disposable school test settings.
    """
    from .workload import WorkloadIntegrityError, summarize_draft_workload

    try:
        school = require_aid_director_access(request.user, school_id=school_id)
    except PermissionDenied:
        return JsonResponse({"detail": "Forbidden."}, status=403)
    except Http404:
        return JsonResponse({"detail": "Not found."}, status=404)

    year = get_object_or_404(
        AcademicYear.objects.for_school(school.pk), pk=academic_year_id
    )
    application_rows = list(
        AidApplication.objects.for_school(school.pk)
        .filter(academic_year_id=year.pk)
        .values("id", "school_id", "academic_year_id", "household_id", "status")
    )
    selection_rows = list(
        AidApplicationStudent.objects.for_school(school.pk)
        .filter(application__academic_year_id=year.pk)
        .values(
            "application_id", "application__school_id",
            "application__academic_year_id", "application__household_id",
            "household_student__household_id", "household_student__student_id",
        )
    )
    try:
        facts = summarize_draft_workload(
            school_id=school.pk,
            academic_year_id=year.pk,
            applications=application_rows,
            selections=selection_rows,
        )
    except WorkloadIntegrityError:
        return JsonResponse({"detail": "Workload unavailable."}, status=503)

    return JsonResponse({
        "school_id": str(school.pk),
        "academic_year_id": str(year.pk),
        **facts,
    })
