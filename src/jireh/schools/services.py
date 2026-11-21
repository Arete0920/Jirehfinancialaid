"""Small, explicit write boundary for student/household relationships."""

from django.db import transaction

from .models import Household, HouseholdStudent, School, Student


@transaction.atomic
def link_student_to_household(*, school_id, household_id, student_id):
    """Create or return a link only when both identities belong to this school.

    This function is an internal domain service, not an authorization
    decision. A future authenticated caller must authorize school and
    household membership before invoking it.
    """
    if not school_id:
        raise ValueError("school_id is required")
    if not School.objects.filter(pk=school_id, is_active=True).exists():
        raise School.DoesNotExist("Active school not found")

    household = Household.objects.for_school(school_id).select_for_update().get(
        pk=household_id, is_active=True
    )
    student = Student.objects.for_school(school_id).select_for_update().get(
        pk=student_id
    )
    link, _created = HouseholdStudent.objects.get_or_create(
        household=household, student=student
    )
    return link
