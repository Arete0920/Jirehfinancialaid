"""Fail-closed school-staff authorization for application inventory."""

from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from jireh.financial_aid.models import AidApplication
from jireh.schools.models import (
    AcademicYear,
    Household,
    HouseholdAccess,
    School,
    SchoolStaffAccess,
    Student,
)


class StaffApplicationReadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.director = User.objects.create_user(
            username="director", password="test-password"
        )
        cls.other_staff = User.objects.create_user(
            username="unassigned", password="test-password"
        )
        cls.parent = User.objects.create_user(
            username="parent", password="test-password"
        )
        cls.superuser = User.objects.create_superuser(
            username="superuser",
            email="admin@example.invalid",
            password="test-password",
        )
        cls.school = School.objects.create(code="first", name="First School")
        cls.other_school = School.objects.create(
            code="second", name="Second School"
        )
        cls.year = AcademicYear.objects.create(
            school=cls.school,
            name="2026-27",
            start_date=date(2026, 8, 1),
            end_date=date(2027, 6, 30),
        )
        cls.other_year = AcademicYear.objects.create(
            school=cls.other_school,
            name="2026-27",
            start_date=date(2026, 8, 1),
            end_date=date(2027, 6, 30),
        )
        cls.house = Household.objects.create(
            school=cls.school, name="First Household"
        )
        cls.other_house = Household.objects.create(
            school=cls.other_school, name="Other Household"
        )
        cls.aid = AidApplication.objects.create(
            school=cls.school,
            academic_year=cls.year,
            household=cls.house,
            created_by=cls.parent,
        )
        cls.other_aid = AidApplication.objects.create(
            school=cls.other_school,
            academic_year=cls.other_year,
            household=cls.other_house,
            created_by=cls.parent,
        )
        HouseholdAccess.objects.create(household=cls.house, user=cls.parent)
        SchoolStaffAccess.objects.create(
            school=cls.school,
            user=cls.director,
            role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        )

    def _url(self, *, school=None, year=None):
        return reverse(
            "jireh_staff_application_index",
            kwargs={
                "school_id": (school or self.school).pk,
                "academic_year_id": (year or self.year).pk,
            },
        )

    def test_authorized_aid_director_sees_only_own_school(self):
        self.client.force_login(self.director)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "school_id": str(self.school.pk),
                "academic_year_id": str(self.year.pk),
                "applications": [
                    {
                        "id": str(self.aid.pk),
                        "household_id": str(self.house.pk),
                        "status": "DRAFT",
                    }
                ],
                "has_more": False,
            },
        )
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertNotIn(str(self.other_aid.pk), response.content.decode())

    def test_anonymous_denied_without_login_redirect(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": "Forbidden."})

    def test_parent_cannot_read_staff_ledger_using_family_grant(self):
        self.client.force_login(self.parent)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Not found."})

    def test_superuser_without_explicit_grant_has_no_bypass(self):
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(self._url()).status_code, 404)

    def test_other_staff_not_automatically_authorized(self):
        self.client.force_login(self.other_staff)
        self.assertEqual(self.client.get(self._url()).status_code, 404)

    def test_role_is_scoped_to_the_school(self):
        self.client.force_login(self.director)
        response = self.client.get(
            self._url(school=self.other_school, year=self.other_year)
        )
        self.assertEqual(response.status_code, 404)

    def test_cross_school_year_produces_not_found(self):
        self.client.force_login(self.director)
        response = self.client.get(self._url(year=self.other_year))
        self.assertEqual(response.status_code, 404)

    def test_claimed_school_header_does_not_confer_access(self):
        self.client.force_login(self.director)
        response = self.client.get(
            self._url(school=self.other_school, year=self.other_year),
            HTTP_X_SCHOOL_ID=str(self.school.pk),
        )
        self.assertEqual(response.status_code, 404)

    def test_inactive_user_is_denied_even_if_granted(self):
        self.client.force_login(self.director)
        self.director.is_active = False
        self.director.save()
        self.assertEqual(self.client.get(self._url()).status_code, 403)

    def test_revocation_denies_immediately(self):
        self.client.force_login(self.director)
        SchoolStaffAccess.objects.for_school(self.school.pk).filter(
            user=self.director
        ).update(is_active=False)
        self.assertEqual(self.client.get(self._url()).status_code, 404)

    def test_inactive_school_denied(self):
        self.client.force_login(self.director)
        self.school.is_active = False
        self.school.save()
        self.assertEqual(self.client.get(self._url()).status_code, 404)

    def test_read_only_route_rejects_mutations(self):
        self.client.force_login(self.director)
        for method in (self.client.post, self.client.put, self.client.delete):
            with self.subTest(method=method.__name__):
                self.assertEqual(method(self._url()).status_code, 405)
        self.assertEqual(AidApplication.objects.count(), 2)

    def test_duplicate_staff_grant_is_blocked(self):
        with self.assertRaises(ValidationError):
            SchoolStaffAccess.objects.create(
                school=self.school,
                user=self.director,
                role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
            )

    def test_unapproved_staff_role_blocked_at_model_and_database(self):
        with self.assertRaises(ValidationError):
            SchoolStaffAccess.objects.create(
                school=self.school, user=self.other_staff, role="SUPPORT"
            )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SchoolStaffAccess.objects.for_school(self.school.pk).filter(
                    user=self.director
                ).update(role="SUPPORT")

    def test_school_roles_do_not_create_household_grants(self):
        self.client.force_login(self.director)
        household_url = reverse(
            "jireh_household_detail",
            kwargs={"school_id": self.school.pk, "household_id": self.house.pk},
        )
        self.assertEqual(self.client.get(household_url).status_code, 404)

    def test_reporting_cap_marks_more_results_without_disclosure(self):
        # Prepare >100 same-school drafts without enabling bulk cross-school writes.
        for number in range(101):
            household = Household.objects.create(
                school=self.school, name=f"Additional Household {number}"
            )
            AidApplication.objects.create(
                school=self.school,
                academic_year=self.year,
                household=household,
                created_by=self.parent,
            )
        self.client.force_login(self.director)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["applications"]), 100)
        self.assertTrue(payload["has_more"])
        self.assertEqual(
            AidApplication.objects.for_school(self.school.pk).count(), 102
        )
