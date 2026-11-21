"""CSRF and household-scope regression tests for family draft HTTP flows."""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from jireh.schools.models import AcademicYear, Household, HouseholdAccess, School, Student
from jireh.schools.services import link_student_to_household

from .models import AidApplication


class FamilyDraftHTTPTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.parent = User.objects.create_user(
            username="parent-a", password="test-password"
        )
        cls.other_parent = User.objects.create_user(
            username="parent-b", password="test-password"
        )
        cls.second_own_parent = User.objects.create_user(
            username="second-own-parent", password="test-password"
        )
        cls.staff = User.objects.create_superuser(
            username="staff-admin", email="admin@example.invalid",
            password="test-password"
        )
        cls.school = School.objects.create(code="first", name="First School")
        cls.other_school = School.objects.create(code="second", name="Second School")
        cls.year = AcademicYear.objects.create(
            school=cls.school,
            name="2026-27",
            start_date=date(2026, 8, 1),
            end_date=date(2027, 6, 30),
        )
        cls.next_year = AcademicYear.objects.create(
            school=cls.school,
            name="2027-28",
            start_date=date(2027, 8, 1),
            end_date=date(2028, 6, 30),
        )
        cls.other_year = AcademicYear.objects.create(
            school=cls.other_school,
            name="2026-27",
            start_date=date(2026, 8, 1),
            end_date=date(2027, 6, 30),
        )
        cls.house = Household.objects.create(
            school=cls.school, name="First Parent Household"
        )
        cls.separated_house = Household.objects.create(
            school=cls.school, name="Second Parent Household"
        )
        cls.other_house = Household.objects.create(
            school=cls.other_school, name="Different School Household"
        )
        cls.child = Student.objects.create(
            school=cls.school, first_name="Sample", last_name="Child"
        )
        cls.sibling = Student.objects.create(
            school=cls.school, first_name="Sample", last_name="Sibling"
        )
        for household in (cls.house, cls.separated_house):
            link_student_to_household(
                school_id=cls.school.pk,
                household_id=household.pk,
                student_id=cls.child.pk,
            )
        link_student_to_household(
            school_id=cls.school.pk,
            household_id=cls.house.pk,
            student_id=cls.sibling.pk,
        )
        for user, household in (
            (cls.parent, cls.house),
            (cls.second_own_parent, cls.house),
            (cls.other_parent, cls.separated_house),
        ):
            HouseholdAccess.objects.create(household=household, user=user)

    def _url(self, *, school=None, household=None, year=None):
        return reverse(
            "jireh_family_annual_draft",
            kwargs={
                "school_id": (school or self.school).pk,
                "household_id": (household or self.house).pk,
                "academic_year_id": (year or self.year).pk,
            },
        )

    def _authenticated_csrf_client(self, user=None):
        client = Client(enforce_csrf_checks=True)
        client.force_login(user or self.parent)
        # GET is read-only and intentionally issues a CSRF cookie.
        response = client.get(self._url())
        self.assertEqual(response.status_code, 404)
        self.assertIn("csrftoken", client.cookies)
        return client, client.cookies["csrftoken"].value

    def test_anonymous_get_is_forbidden_not_redirected(self):
        client = Client(enforce_csrf_checks=True)
        response = client.get(self._url())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": "Forbidden."})

    def test_authenticated_get_without_draft_does_not_create(self):
        self.client.force_login(self.parent)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 404)
        self.assertFalse(AidApplication.objects.exists())

    def test_post_without_csrf_does_not_create_even_if_authenticated(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.parent)
        response = client.post(self._url())
        self.assertEqual(response.status_code, 403)
        self.assertFalse(AidApplication.objects.exists())

    def test_post_with_csrf_creates_one_draft_and_get_resumes(self):
        client, token = self._authenticated_csrf_client()
        post = client.post(self._url(), HTTP_X_CSRFTOKEN=token)
        self.assertEqual(post.status_code, 200)
        self.assertEqual(
            post.json(),
            {
                "id": str(AidApplication.objects.get().pk),
                "school_id": str(self.school.pk),
                "household_id": str(self.house.pk),
                "academic_year_id": str(self.year.pk),
                "status": "DRAFT",
            },
        )
        self.assertIn("no-store", post.headers["Cache-Control"])
        resumed = client.get(self._url())
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(resumed.json(), post.json())

    def test_repeat_post_is_idempotent_and_preserves_original_creator(self):
        client, token = self._authenticated_csrf_client()
        first = client.post(self._url(), HTTP_X_CSRFTOKEN=token)
        second = client.post(self._url(), HTTP_X_CSRFTOKEN=token)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(AidApplication.objects.count(), 1)
        self.assertEqual(AidApplication.objects.get().created_by_id, self.parent.pk)

    def test_second_authorized_parent_resumes_same_household_draft(self):
        client, token = self._authenticated_csrf_client()
        first = client.post(self._url(), HTTP_X_CSRFTOKEN=token)
        self.assertEqual(first.status_code, 200)
        second = Client(enforce_csrf_checks=True)
        second.force_login(self.second_own_parent)
        resumed = second.get(self._url())
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(resumed.json()["id"], first.json()["id"])

    def test_separated_households_sharing_child_keep_separate_drafts(self):
        client, token = self._authenticated_csrf_client()
        first = client.post(self._url(), HTTP_X_CSRFTOKEN=token)
        other_url = self._url(household=self.separated_house)
        self.assertEqual(client.get(other_url).status_code, 404)
        self.assertEqual(
            client.post(other_url, HTTP_X_CSRFTOKEN=token).status_code, 404
        )
        separate = Client(enforce_csrf_checks=True)
        separate.force_login(self.other_parent)
        self.assertEqual(separate.get(other_url).status_code, 404)
        other_token = separate.cookies["csrftoken"].value
        other = separate.post(other_url, HTTP_X_CSRFTOKEN=other_token)
        self.assertEqual(other.status_code, 200)
        self.assertNotEqual(first.json()["id"], other.json()["id"])
        self.assertEqual(AidApplication.objects.count(), 2)

    def test_same_household_different_school_year_has_distinct_draft(self):
        client, token = self._authenticated_csrf_client()
        first = client.post(self._url(), HTTP_X_CSRFTOKEN=token)
        second = client.post(
            self._url(year=self.next_year),
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(AidApplication.objects.count(), 2)

    def test_cross_school_year_and_spoofed_header_are_denied(self):
        client, token = self._authenticated_csrf_client()
        for url in (
            self._url(year=self.other_year),
            self._url(school=self.other_school, year=self.other_year),
            self._url(school=self.other_school, household=self.other_house,
                      year=self.other_year),
        ):
            with self.subTest(url=url):
                response = client.post(
                    url, HTTP_X_CSRFTOKEN=token,
                    HTTP_X_SCHOOL_ID=str(self.school.pk),
                )
                self.assertEqual(response.status_code, 404)
        self.assertFalse(AidApplication.objects.exists())

    def test_revoked_grant_rejects_get_and_post(self):
        client, token = self._authenticated_csrf_client()
        self.assertEqual(
            client.post(self._url(), HTTP_X_CSRFTOKEN=token).status_code, 200
        )
        HouseholdAccess.objects.filter(
            household=self.house, user=self.parent
        ).update(is_active=False)
        self.assertEqual(client.get(self._url()).status_code, 404)
        self.assertEqual(
            client.post(self._url(), HTTP_X_CSRFTOKEN=token).status_code, 404
        )
        self.assertEqual(AidApplication.objects.count(), 1)

    def test_inactive_household_and_school_are_denied(self):
        client, token = self._authenticated_csrf_client()
        self.house.is_active = False
        self.house.save()
        self.assertEqual(
            client.post(self._url(), HTTP_X_CSRFTOKEN=token).status_code, 404
        )
        self.house.is_active = True
        self.house.save()
        self.school.is_active = False
        self.school.save()
        self.assertEqual(
            client.post(self._url(), HTTP_X_CSRFTOKEN=token).status_code, 404
        )
        self.assertFalse(AidApplication.objects.exists())

    def test_inactive_user_is_forbidden(self):
        client, token = self._authenticated_csrf_client()
        self.parent.is_active = False
        self.parent.save()
        self.assertEqual(
            client.post(self._url(), HTTP_X_CSRFTOKEN=token).status_code, 403
        )
        self.assertFalse(AidApplication.objects.exists())

    def test_superuser_without_grant_cannot_create_draft(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff)
        self.assertEqual(client.get(self._url()).status_code, 404)
        token = client.cookies["csrftoken"].value
        self.assertEqual(
            client.post(self._url(), HTTP_X_CSRFTOKEN=token).status_code, 404
        )
        self.assertFalse(AidApplication.objects.exists())

    def test_wrong_method_does_not_modify_data(self):
        self.client.force_login(self.parent)
        for method in (self.client.put, self.client.patch, self.client.delete):
            with self.subTest(method=method.__name__):
                self.assertEqual(method(self._url()).status_code, 405)
        self.assertFalse(AidApplication.objects.exists())

    def test_post_returns_only_identifiers_and_status(self):
        client, token = self._authenticated_csrf_client()
        response = client.post(self._url(), HTTP_X_CSRFTOKEN=token)
        self.assertEqual(
            set(response.json()),
            {"id", "school_id", "household_id", "academic_year_id", "status"},
        )
        self.assertNotIn("income", response.content.decode())
        self.assertNotIn("payment", response.content.decode())
