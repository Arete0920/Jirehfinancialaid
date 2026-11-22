"""Synthetic-only browser demo fixtures. Never provision actual schools here."""

import secrets
from datetime import date

from django.contrib.auth import get_user_model
from django.db import transaction

from jireh.schools.models import (
    AcademicYear,
    Household,
    HouseholdAccess,
    School,
    SchoolStaffAccess,
    Student,
)
from jireh.schools.services import link_student_to_household


DEMO_SCHOOL_A_CODE = "local-jireh-school-a"
DEMO_SCHOOL_B_CODE = "local-jireh-school-b"
DEMO_PARENT = "local-demo-family"
DEMO_DIRECTOR_A = "local-demo-director-a"
DEMO_DIRECTOR_B = "local-demo-director-b"
DEMO_PASSWORD = secrets.token_urlsafe(32)


@transaction.atomic
def seed_synthetic_browser_demo():
    """Seed an empty, disposable database with no personal or financial data."""
    if School.objects.filter(
        code__in=[DEMO_SCHOOL_A_CODE, DEMO_SCHOOL_B_CODE]
    ).exists():
        raise RuntimeError("Synthetic demo schools already exist; use a fresh database.")

    User = get_user_model()
    parent = User.objects.create_user(username=DEMO_PARENT, password=DEMO_PASSWORD)
    director_a = User.objects.create_user(
        username=DEMO_DIRECTOR_A, password=DEMO_PASSWORD,
    )
    director_b = User.objects.create_user(
        username=DEMO_DIRECTOR_B, password=DEMO_PASSWORD,
    )

    school_a = School.objects.create(
        code=DEMO_SCHOOL_A_CODE, name="Synthetic Christian Academy",
    )
    school_b = School.objects.create(
        code=DEMO_SCHOOL_B_CODE, name="Synthetic School B",
    )
    year_a = AcademicYear.objects.create(
        school=school_a, name="2026-27",
        start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
    )
    year_b = AcademicYear.objects.create(
        school=school_b, name="2026-27",
        start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
    )
    household_a = Household.objects.create(
        school=school_a, name="Sample Family",
    )
    household_b = Household.objects.create(
        school=school_b, name="Unrelated Family",
    )
    student_a1 = Student.objects.create(
        school=school_a, first_name="Jordan", last_name="Sample",
    )
    student_a2 = Student.objects.create(
        school=school_a, first_name="Taylor", last_name="Sample",
    )
    student_b = Student.objects.create(
        school=school_b, first_name="Alex", last_name="Example",
    )
    for household, student in (
        (household_a, student_a1),
        (household_a, student_a2),
        (household_b, student_b),
    ):
        link_student_to_household(
            school_id=household.school_id,
            household_id=household.pk,
            student_id=student.pk,
        )

    HouseholdAccess.objects.create(household=household_a, user=parent)
    for school, director in ((school_a, director_a), (school_b, director_b)):
        SchoolStaffAccess.objects.create(
            school=school,
            user=director,
            role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        )
    return {
        "school_a": school_a,
        "school_b": school_b,
        "household_a": household_a,
        "household_b": household_b,
        "year_a": year_a,
        "year_b": year_b,
        "parent": parent,
        "director_a": director_a,
        "director_b": director_b,
    }
