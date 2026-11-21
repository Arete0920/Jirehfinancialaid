"""Authorized, idempotent household draft creation and retrieval."""

from django.core.exceptions import ValidationError
from django.db import transaction

from jireh.schools.access import require_household_access
from jireh.schools.models import AcademicYear

from .models import AidApplication


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
