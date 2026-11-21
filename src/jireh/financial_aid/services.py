"""Authorized, idempotent household draft creation and retrieval."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404

from jireh.schools.access import require_household_access
from jireh.schools.models import AcademicYear, HouseholdStudent

from .models import AidApplication, AidApplicationStudent


@transaction.atomic
def get_or_create_annual_draft(
    *, user, school_id, household_id, academic_year_id
):
    """Return one DRAFT per household/year, without charging or submitting.

    The caller must hold an explicit active grant to this household. Two
    authorized members of one household share the same annual draft; members
    of separate households sharing a student do not share application access.
    """
    household = require_household_access(
        user, school_id=school_id, household_id=household_id
    )
    year = AcademicYear.objects.for_school(school_id).get(pk=academic_year_id)

    application, _created = AidApplication.objects.get_or_create(
        school=household.school,
        academic_year=year,
        household=household,
        defaults={
            "created_by": user,
            "status": AidApplication.STATUS_DRAFT,
        },
    )
    if application.status != AidApplication.STATUS_DRAFT:
        raise ValidationError("Only an existing draft may be resumed.")
    return application


def _require_existing_draft(*, user, school_id, household_id, academic_year_id, lock=False):
    """Authorize household before checking whether a draft or year exists."""
    household = require_household_access(
        user, school_id=school_id, household_id=household_id
    )
    if not AcademicYear.objects.for_school(household.school_id).filter(
        pk=academic_year_id
    ).exists():
        raise Http404("Draft not found.")

    query = AidApplication.objects.for_school(household.school_id).filter(
        household_id=household.pk,
        academic_year_id=academic_year_id,
        status=AidApplication.STATUS_DRAFT,
    )
    if lock:
        query = query.select_for_update()
    draft = query.first()
    if draft is None:
        raise Http404("Draft not found.")
    return draft


def selected_student_ids_for_draft(
    *, user, school_id, household_id, academic_year_id
):
    """Return student UUIDs for this authorized existing draft only."""
    draft = _require_existing_draft(
        user=user, school_id=school_id, household_id=household_id,
        academic_year_id=academic_year_id,
    )
    student_ids = (
        AidApplicationStudent.objects.for_school(draft.school_id)
        .filter(
            application_id=draft.pk,
            household_student__household_id=draft.household_id,
        )
        .order_by("household_student__student_id")
        .values_list("household_student__student_id", flat=True)
    )
    return draft, list(student_ids)


@transaction.atomic
def select_student_for_draft(
    *, user, school_id, household_id, academic_year_id, student_id
):
    """Idempotently include a child already linked to the exact household.

    Creating a selection cannot create a draft or a student-household link.
    No financial assessment, submission, fee or grant of access occurs.
    """
    draft = _require_existing_draft(
        user=user, school_id=school_id, household_id=household_id,
        academic_year_id=academic_year_id, lock=True,
    )
    link = (
        HouseholdStudent.objects.for_school(draft.school_id)
        .filter(household_id=draft.household_id, student_id=student_id)
        .first()
    )
    if link is None:
        raise Http404("Student not linked to this household.")

    selection, _created = AidApplicationStudent.objects.get_or_create(
        application=draft, household_student=link
    )
    return selection
