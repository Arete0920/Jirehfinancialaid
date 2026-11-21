"""Draft lifecycle, identity separation and annual uniqueness tests."""

from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.test import TestCase

from jireh.schools.models import (
    AcademicYear,
    Household,
    HouseholdAccess,
    School,
    Student,
)
from jireh.schools.services import link_student_to_household

from .models import AidApplication
from .services import get_or_create_annual_draft


class HouseholdDraftTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school_a = School.objects.create(code="school-a", name="School A")
        cls.school_b = School.objects.create(code="school-b", name="School B")
        cls.year_a = AcademicYear.objects.create(
            school=cls.school_a,
            name="2026-27",
            start_date=date(2026, 8, 1),
            end_date=date(2027, 6, 30),
        )
        cls.year_next = AcademicYear.objects.create(
            school=cls.school_a,
            name="2027-28",
            start_date=date(2027, 8, 1),
            end_date=date(2028, 6, 30),
        )
        cls.year_b = AcademicYear.objects.create(
            school=cls.school_b,
            name="2026-27",
            start_date=date(2026, 8, 1),
            end_date=date(2027, 6, 30),
        )
        cls.house_a = Household.objects.create(
            school=cls.school_a, name="House A"
        )
        cls.house_separate = Household.objects.create(
            school=cls.school_a, name="Separate Household"
        )
        cls.house_b = Household.objects.create(
            school=cls.school_b, name="House B"
        )
        cls.child = Student.objects.create(
            school=cls.school_a, first_name="Sample", last_name="Child"
        )
        cls.sibling = Student.objects.create(
            school=cls.school_a, first_name="Second", last_name="Child"
        )
        for household in (cls.house_a, cls.house_separate):
            link_student_to_household(
                school_id=cls.school_a.pk,
                household_id=household.pk,
                student_id=cls.child.pk,
            )
        link_student_to_household(
            school_id=cls.school_a.pk,
            household_id=cls.house_a.pk,
            student_id=cls.sibling.pk,
        )
        User = get_user_model()
        cls.parent = User.objects.create_user(
            username="parent", password="test-password"
        )
        cls.same_household_parent = User.objects.create_user(
            username="same_household_parent", password="test-password"
        )
        cls.other = User.objects.create_user(
            username="other", password="test-password"
        )
        HouseholdAccess.objects.create(
            household=cls.house_a, user=cls.parent
        )
        HouseholdAccess.objects.create(
            household=cls.house_a, user=cls.same_household_parent
        )
        HouseholdAccess.objects.create(
            household=cls.house_separate, user=cls.other
        )

    def _draft(self, *, user=None, school=None, household=None, year=None):
        return get_or_create_annual_draft(
            user=self.parent if user is None else user,
            school_id=(school or self.school_a).pk,
            household_id=(household or self.house_a).pk,
            academic_year_id=(year or self.year_a).pk,
        )

    def test_first_creation_starts_draft_and_records_actor(self):
        application = self._draft()
        self.assertEqual(application.status, AidApplication.STATUS_DRAFT)
        self.assertEqual(application.school_id, self.school_a.pk)
        self.assertEqual(application.academic_year_id, self.year_a.pk)
        self.assertEqual(application.household_id, self.house_a.pk)
        self.assertEqual(application.created_by_id, self.parent.pk)

    def test_repeat_request_returns_same_draft_with_original_creator(self):
        first = self._draft()
        again = self._draft(user=self.same_household_parent)
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(again.created_by_id, self.parent.pk)
        self.assertEqual(AidApplication.objects.count(), 1)

    def test_multiple_children_share_household_application(self):
        draft = self._draft()
        self.assertEqual(self.house_a.student_links.count(), 2)
        self.assertEqual(AidApplication.objects.filter(household=self.house_a).count(), 1)
        self.assertEqual(draft.household_id, self.house_a.pk)

    def test_two_households_sharing_student_have_separate_drafts(self):
        original = self._draft()
        independent = self._draft(user=self.other, household=self.house_separate)
        self.assertNotEqual(original.pk, independent.pk)
        self.assertEqual(AidApplication.objects.count(), 2)

    def test_new_academic_year_requires_separate_draft(self):
        first = self._draft()
        second = self._draft(year=self.year_next)
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(AidApplication.objects.for_school(self.school_a.pk).count(), 2)

    def test_cross_school_academic_year_is_rejected_without_creation(self):
        with self.assertRaises(AcademicYear.DoesNotExist):
            self._draft(year=self.year_b)
        self.assertFalse(AidApplication.objects.exists())

    def test_cross_school_household_and_school_spoofing_are_denied(self):
        for kwargs in (
            {"household": self.house_b},
            {"school": self.school_b},
            {"household": self.house_separate},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(Http404):
                    self._draft(**kwargs)
        self.assertFalse(AidApplication.objects.exists())

    def test_unauthorized_user_and_anonymous_principal_cannot_create(self):
        from django.contrib.auth.models import AnonymousUser
        with self.assertRaises(PermissionDenied):
            self._draft(user=AnonymousUser())
        with self.assertRaises(Http404):
            self._draft(user=self.other)
        self.assertFalse(AidApplication.objects.exists())

    def test_revoked_access_blocks_new_and_existing_draft_retrieval(self):
        existing = self._draft()
        self.assertIsNotNone(existing)
        HouseholdAccess.objects.filter(
            household=self.house_a, user=self.parent
        ).update(is_active=False)
        with self.assertRaises(Http404):
            self._draft()
        self.assertEqual(AidApplication.objects.count(), 1)

    def test_inactive_school_and_household_are_denied(self):
        self.house_a.is_active = False
        self.house_a.save()
        with self.assertRaises(Http404):
            self._draft()
        self.house_a.is_active = True
        self.house_a.save()
        self.school_a.is_active = False
        self.school_a.save()
        with self.assertRaises(Http404):
            self._draft()

    def test_model_rejects_cross_school_year_and_household(self):
        with self.assertRaises(ValidationError):
            AidApplication.objects.create(
                school=self.school_a,
                academic_year=self.year_b,
                household=self.house_a,
                created_by=self.parent,
            )
        with self.assertRaises(ValidationError):
            AidApplication.objects.create(
                school=self.school_a,
                academic_year=self.year_a,
                household=self.house_b,
                created_by=self.parent,
            )
        self.assertFalse(AidApplication.objects.exists())

    def test_database_enforces_unique_household_school_year(self):
        original = self._draft()
        with self.assertRaises(ValidationError):
            AidApplication.objects.create(
                school=self.school_a,
                academic_year=self.year_a,
                household=self.house_a,
                created_by=self.same_household_parent,
            )
        other = self._draft(year=self.year_next)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AidApplication.objects.filter(pk=other.pk).update(
                    academic_year_id=self.year_a.pk
                )
        self.assertEqual(
            AidApplication.objects.get(pk=original.pk).academic_year_id,
            self.year_a.pk,
        )

    def test_invalid_lifecycle_transition_is_not_enabled(self):
        draft = self._draft()
        draft.status = "SUBMITTED"
        with self.assertRaises(ValidationError):
            draft.save()
        draft.refresh_from_db()
        self.assertEqual(draft.status, "DRAFT")

    def test_no_fees_or_sensitive_financial_fields_in_draft_schema(self):
        names = {field.name for field in AidApplication._meta.fields}
        self.assertFalse(
            names.intersection(
                {
                    "payment",
                    "fee_paid",
                    "tax_document",
                    "income",
                    "assets",
                    "liabilities",
                    "religion",
                }
            )
        )
        self.assertEqual(self._draft().status, "DRAFT")
