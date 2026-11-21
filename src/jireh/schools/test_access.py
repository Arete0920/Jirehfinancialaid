"""HTTP authorization tests: school, household and child separation."""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import Household, HouseholdAccess, School, Student
from .services import link_student_to_household


class HouseholdAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school_a = School.objects.create(code="a", name="School A")
        cls.school_b = School.objects.create(code="b", name="School B")
        cls.house_a = Household.objects.create(
            school=cls.school_a, name="First Parent"
        )
        cls.house_separate = Household.objects.create(
            school=cls.school_a, name="Second Parent"
        )
        cls.house_b = Household.objects.create(
            school=cls.school_b, name="Another School"
        )
        cls.child_a = Student.objects.create(
            school=cls.school_a, first_name="Child", last_name="A"
        )
        cls.child_b = Student.objects.create(
            school=cls.school_b, first_name="Child", last_name="B"
        )
        for household in (cls.house_a, cls.house_separate):
            link_student_to_household(
                school_id=cls.school_a.pk,
                household_id=household.pk,
                student_id=cls.child_a.pk,
            )
        link_student_to_household(
            school_id=cls.school_b.pk,
            household_id=cls.house_b.pk,
            student_id=cls.child_b.pk,
        )
        User = get_user_model()
        cls.parent = User.objects.create_user(
            username="parent_a", password="test-password"
        )
        cls.other = User.objects.create_user(
            username="parent_b", password="test-password"
        )
        cls.staff_without_grant = User.objects.create_superuser(
            username="staff", email="staff@example.invalid", password="test-password"
        )
        HouseholdAccess.objects.create(
            household=cls.house_a, user=cls.parent
        )

    def _url(self, household, *, school=None, students=True):
        return reverse(
            "jireh_household_students" if students else "jireh_household_detail",
            kwargs={
                "school_id": (school or household.school).pk,
                "household_id": household.pk,
            },
        )

    def test_anonymous_request_is_forbidden_not_redirected(self):
        response = self.client.get(self._url(self.house_a))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": "Forbidden."})

    def test_explicit_grant_returns_only_own_household_students(self):
        self.client.force_login(self.parent)
        response = self.client.get(self._url(self.house_a))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "household_id": str(self.house_a.pk),
                "students": [
                    {
                        "id": str(self.child_a.pk),
                        "first_name": "Child",
                        "last_name": "A",
                    }
                ],
            },
        )
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_explicit_grant_permits_only_own_household_details(self):
        self.client.force_login(self.parent)
        response = self.client.get(self._url(self.house_a, students=False))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"id": str(self.house_a.pk), "name": "First Parent"},
        )

    def test_same_child_in_two_households_does_not_share_access(self):
        self.client.force_login(self.parent)
        response = self.client.get(self._url(self.house_separate))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Not found."})
        response = self.client.get(
            self._url(self.house_separate, students=False)
        )
        self.assertEqual(response.status_code, 404)

    def test_cross_school_or_header_spoofing_is_denied(self):
        self.client.force_login(self.parent)
        for url in (
            self._url(self.house_b),
            self._url(self.house_a, school=self.school_b),
        ):
            with self.subTest(url=url):
                response = self.client.get(url, HTTP_X_SCHOOL_ID=str(self.school_a.pk))
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json(), {"detail": "Not found."})

    def test_other_user_does_not_inherit_grant_or_school_access(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self._url(self.house_a)).status_code, 404)

    def test_staff_and_superuser_do_not_bypass_family_grants(self):
        self.client.force_login(self.staff_without_grant)
        self.assertEqual(self.client.get(self._url(self.house_a)).status_code, 404)

    def test_grant_revocation_immediately_denies_access(self):
        self.client.force_login(self.parent)
        HouseholdAccess.objects.filter(
            household=self.house_a, user=self.parent
        ).update(is_active=False)
        self.assertEqual(self.client.get(self._url(self.house_a)).status_code, 404)

    def test_inactive_school_or_household_denies_access(self):
        self.client.force_login(self.parent)
        self.house_a.is_active = False
        self.house_a.save()
        self.assertEqual(self.client.get(self._url(self.house_a)).status_code, 404)
        self.house_a.is_active = True
        self.house_a.save()
        self.school_a.is_active = False
        self.school_a.save()
        self.assertEqual(self.client.get(self._url(self.house_a)).status_code, 404)

    def test_deactivated_user_cannot_continue_using_session(self):
        self.client.force_login(self.parent)
        self.parent.is_active = False
        self.parent.save()
        response = self.client.get(self._url(self.house_a))
        self.assertEqual(response.status_code, 403)

    def test_account_requires_explicit_grant_for_each_school(self):
        HouseholdAccess.objects.create(
            household=self.house_b, user=self.parent
        )
        self.client.force_login(self.parent)
        response = self.client.get(self._url(self.house_b))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["students"][0]["id"], str(self.child_b.pk))
        self.assertEqual(self.client.get(self._url(self.house_separate)).status_code, 404)

    def test_duplicate_access_grant_is_rejected(self):
        with self.assertRaises(ValidationError):
            HouseholdAccess.objects.create(
                household=self.house_a, user=self.parent
            )
        self.assertEqual(
            HouseholdAccess.objects.filter(
                household=self.house_a, user=self.parent
            ).count(),
            1,
        )

    def test_mutating_requests_are_not_supported(self):
        self.client.force_login(self.parent)
        for method in (self.client.post, self.client.put, self.client.delete):
            with self.subTest(method=method.__name__):
                self.assertEqual(method(self._url(self.house_a)).status_code, 405)
