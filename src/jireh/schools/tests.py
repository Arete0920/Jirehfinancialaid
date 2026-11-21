"""Database-level regression tests for standalone school and family identity."""

from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import AcademicYear, Household, HouseholdStudent, School, Student
from .services import link_student_to_household


class SchoolHouseholdTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school_a = School.objects.create(code="school-a", name="Independent School")
        cls.school_b = School.objects.create(code="school-b", name="Independent School")
        cls.year_a = AcademicYear.objects.create(
            school=cls.school_a, name="2026-27",
            start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
        )
        cls.household_a = Household.objects.create(
            school=cls.school_a, name="Household One"
        )
        cls.household_b = Household.objects.create(
            school=cls.school_b, name="Household One"
        )
        cls.student_a = Student.objects.create(
            school=cls.school_a, first_name="Sample", last_name="Student"
        )
        cls.student_b = Student.objects.create(
            school=cls.school_b, first_name="Sample", last_name="Student"
        )

    def test_duplicate_school_code_is_rejected(self):
        with self.assertRaises(ValidationError):
            School.objects.create(code="school-a", name="Different School")

    def test_household_labels_do_not_define_global_identity(self):
        second = Household.objects.create(
            school=self.school_a, name="Household One"
        )
        self.assertNotEqual(second.pk, self.household_a.pk)
        self.assertNotEqual(self.household_a.pk, self.household_b.pk)

    def test_academic_year_is_unique_within_school_only(self):
        AcademicYear.objects.create(
            school=self.school_b, name="2026-27",
            start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
        )
        with self.assertRaises(ValidationError):
            AcademicYear.objects.create(
                school=self.school_a, name="2026-27",
                start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
            )

    def test_invalid_academic_year_is_blocked_by_model_and_database(self):
        with self.assertRaises(ValidationError):
            AcademicYear.objects.create(
                school=self.school_a, name="bad",
                start_date=date(2027, 7, 1), end_date=date(2027, 6, 30),
            )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AcademicYear.objects.filter(pk=self.year_a.pk).update(
                    end_date=date(2026, 1, 1)
                )

    def test_multiple_children_under_one_household(self):
        second = Student.objects.create(
            school=self.school_a, first_name="Other", last_name="Student"
        )
        link_student_to_household(
            school_id=self.school_a.pk,
            household_id=self.household_a.pk,
            student_id=self.student_a.pk,
        )
        link_student_to_household(
            school_id=self.school_a.pk,
            household_id=self.household_a.pk,
            student_id=second.pk,
        )
        self.assertEqual(
            HouseholdStudent.objects.for_school(self.school_a.pk).count(), 2
        )

    def test_same_child_can_have_separate_households(self):
        second_household = Household.objects.create(
            school=self.school_a, name="Separate Parent Household"
        )
        link_student_to_household(
            school_id=self.school_a.pk,
            household_id=self.household_a.pk,
            student_id=self.student_a.pk,
        )
        link_student_to_household(
            school_id=self.school_a.pk,
            household_id=second_household.pk,
            student_id=self.student_a.pk,
        )
        self.assertEqual(
            HouseholdStudent.objects.for_school(self.school_a.pk).filter(
                student=self.student_a
            ).count(), 2
        )
        self.assertEqual(
            Household.objects.for_school(self.school_a.pk).count(), 2
        )

    def test_link_creation_is_idempotent(self):
        arguments = {
            "school_id": self.school_a.pk,
            "household_id": self.household_a.pk,
            "student_id": self.student_a.pk,
        }
        first = link_student_to_household(**arguments)
        second = link_student_to_household(**arguments)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(HouseholdStudent.objects.count(), 1)

    def test_cross_school_link_is_rejected_in_service_and_direct_save(self):
        with self.assertRaises(Student.DoesNotExist):
            link_student_to_household(
                school_id=self.school_a.pk,
                household_id=self.household_a.pk,
                student_id=self.student_b.pk,
            )
        with self.assertRaises(Household.DoesNotExist):
            link_student_to_household(
                school_id=self.school_b.pk,
                household_id=self.household_a.pk,
                student_id=self.student_b.pk,
            )
        with self.assertRaises(ValidationError):
            HouseholdStudent(
                household=self.household_a, student=self.student_b
            ).save()
        self.assertFalse(HouseholdStudent.objects.exists())

    def test_school_scope_filters_all_related_domains(self):
        self.assertEqual(
            list(Household.objects.for_school(self.school_a.pk)),
            [self.household_a],
        )
        self.assertEqual(
            list(Student.objects.for_school(self.school_b.pk)),
            [self.student_b],
        )
        self.assertEqual(
            list(AcademicYear.objects.for_school(self.school_b.pk)), [],
        )
        link_student_to_household(
            school_id=self.school_a.pk,
            household_id=self.household_a.pk,
            student_id=self.student_a.pk,
        )
        self.assertEqual(
            HouseholdStudent.objects.for_school(self.school_b.pk).count(), 0
        )

    def test_missing_or_inactive_school_fails_closed(self):
        for model in (AcademicYear, Household, Student, HouseholdStudent):
            with self.subTest(model=model.__name__):
                with self.assertRaises(ValueError):
                    model.objects.for_school(None)
        with self.assertRaises(ValueError):
            link_student_to_household(
                school_id=None,
                household_id=self.household_a.pk,
                student_id=self.student_a.pk,
            )
        self.school_a.is_active = False
        self.school_a.save()
        with self.assertRaises(School.DoesNotExist):
            link_student_to_household(
                school_id=self.school_a.pk,
                household_id=self.household_a.pk,
                student_id=self.student_a.pk,
            )
