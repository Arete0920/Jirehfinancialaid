"""Student selection integrity and household authorization regressions."""

from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.http import Http404
from django.test import Client, TestCase
from django.urls import reverse

from jireh.schools.models import (
    AcademicYear, Household, HouseholdAccess, HouseholdStudent, School, Student,
)
from jireh.schools.services import link_student_to_household

from .models import AidApplicationStudent
from .services import (
    get_or_create_annual_draft,
    select_student_for_draft,
    selected_student_ids_for_draft,
)


class AnnualDraftStudentSelectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.parent = User.objects.create_user(
            username="first-parent", password="test-password"
        )
        cls.separate_parent = User.objects.create_user(
            username="separate-parent", password="test-password"
        )
        cls.unassigned = User.objects.create_user(
            username="unassigned", password="test-password"
        )
        cls.admin = User.objects.create_superuser(
            username="admin", email="admin@example.invalid",
            password="test-password",
        )
        cls.school = School.objects.create(code="school-a", name="School A")
        cls.other_school = School.objects.create(code="school-b", name="School B")
        cls.year = AcademicYear.objects.create(
            school=cls.school, name="2026-27",
            start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
        )
        cls.next_year = AcademicYear.objects.create(
            school=cls.school, name="2027-28",
            start_date=date(2027, 8, 1), end_date=date(2028, 6, 30),
        )
        cls.other_year = AcademicYear.objects.create(
            school=cls.other_school, name="2026-27",
            start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
        )
        cls.household = Household.objects.create(
            school=cls.school, name="Primary household"
        )
        cls.separate_household = Household.objects.create(
            school=cls.school, name="Separate-parent household"
        )
        cls.other_household = Household.objects.create(
            school=cls.other_school, name="Unrelated school"
        )
        cls.child = Student.objects.create(
            school=cls.school, first_name="Child", last_name="One"
        )
        cls.sibling = Student.objects.create(
            school=cls.school, first_name="Child", last_name="Two"
        )
        cls.unlinked = Student.objects.create(
            school=cls.school, first_name="Unlinked", last_name="Child"
        )
        cls.other_school_child = Student.objects.create(
            school=cls.other_school, first_name="Other", last_name="School"
        )
        for household, student in (
            (cls.household, cls.child),
            (cls.household, cls.sibling),
            (cls.separate_household, cls.child),
            (cls.other_household, cls.other_school_child),
        ):
            link_student_to_household(
                school_id=household.school_id,
                household_id=household.pk,
                student_id=student.pk,
            )
        HouseholdAccess.objects.create(
            household=cls.household, user=cls.parent
        )
        HouseholdAccess.objects.create(
            household=cls.separate_household, user=cls.separate_parent
        )
        cls.primary_draft = get_or_create_annual_draft(
            user=cls.parent, school_id=cls.school.pk,
            household_id=cls.household.pk, academic_year_id=cls.year.pk,
        )
        cls.separate_draft = get_or_create_annual_draft(
            user=cls.separate_parent, school_id=cls.school.pk,
            household_id=cls.separate_household.pk, academic_year_id=cls.year.pk,
        )

    def _args(self, *, user=None, household=None, school=None, year=None, student=None):
        return {
            "user": self.parent if user is None else user,
            "school_id": (school or self.school).pk,
            "household_id": (household or self.household).pk,
            "academic_year_id": (year or self.year).pk,
            "student_id": (student or self.child).pk,
        }

    def _list_url(self, *, school=None, household=None, year=None):
        return reverse(
            "jireh_aid_selected_students",
            kwargs={
                "school_id": (school or self.school).pk,
                "household_id": (household or self.household).pk,
                "academic_year_id": (year or self.year).pk,
            },
        )

    def _select_url(self, *, student=None, school=None, household=None, year=None):
        return reverse(
            "jireh_aid_select_student",
            kwargs={
                "school_id": (school or self.school).pk,
                "household_id": (household or self.household).pk,
                "academic_year_id": (year or self.year).pk,
                "student_id": (student or self.child).pk,
            },
        )

    def _csrf_client(self, *, user=None, household=None):
        user = self.parent if user is None else user
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        response = client.get(self._list_url(household=household))
        self.assertEqual(response.status_code, 200)
        self.assertIn("csrftoken", client.cookies)
        return client, client.cookies["csrftoken"].value

    def test_existing_draft_starts_with_no_selected_students(self):
        client, _ = self._csrf_client()
        response = client.get(self._list_url())
        self.assertEqual(response.json(), {
            "application_id": str(self.primary_draft.pk),
            "student_ids": [],
        })
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_select_child_is_idempotent(self):
        client, token = self._csrf_client()
        first = client.post(
            self._select_url(), HTTP_X_CSRFTOKEN=token
        )
        again = client.post(
            self._select_url(), HTTP_X_CSRFTOKEN=token
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), again.json())
        self.assertEqual(AidApplicationStudent.objects.count(), 1)
        self.assertEqual(
            client.get(self._list_url()).json()["student_ids"], [str(self.child.pk)]
        )

    def test_multiple_children_one_household_one_application(self):
        client, token = self._csrf_client()
        for student in (self.child, self.sibling):
            self.assertEqual(
                client.post(
                    self._select_url(student=student),
                    HTTP_X_CSRFTOKEN=token,
                ).status_code,
                200,
            )
        self.assertEqual(AidApplicationStudent.objects.count(), 2)
        self.assertEqual(len(client.get(self._list_url()).json()["student_ids"]), 2)
        self.assertEqual(
            {x.application_id for x in AidApplicationStudent.objects.all()},
            {self.primary_draft.pk},
        )

    def test_separate_households_same_child_have_independent_selection(self):
        client, token = self._csrf_client()
        first = client.post(self._select_url(), HTTP_X_CSRFTOKEN=token)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(
            client.get(self._list_url(household=self.separate_household)).status_code,
            404,
        )
        other, token2 = self._csrf_client(
            user=self.separate_parent, household=self.separate_household
        )
        self.assertEqual(
            other.get(self._list_url(household=self.separate_household))
            .json()["student_ids"], [],
        )
        second = other.post(
            self._select_url(household=self.separate_household),
            HTTP_X_CSRFTOKEN=token2,
        )
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(first.json()["selection_id"], second.json()["selection_id"])
        self.assertNotEqual(
            first.json()["application_id"], second.json()["application_id"]
        )
        self.assertEqual(AidApplicationStudent.objects.count(), 2)

    def test_unlinked_same_school_student_denied(self):
        client, token = self._csrf_client()
        resp = client.post(
            self._select_url(student=self.unlinked),
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(AidApplicationStudent.objects.exists())

    def test_cross_school_student_denied_with_spoofed_header(self):
        client, token = self._csrf_client()
        resp = client.post(
            self._select_url(student=self.other_school_child),
            HTTP_X_CSRFTOKEN=token,
            HTTP_X_SCHOOL_ID=str(self.other_school.pk),
        )
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(AidApplicationStudent.objects.exists())

    def test_cross_school_and_wrong_year_denied(self):
        client, token = self._csrf_client()
        for url in (
            self._select_url(year=self.other_year),
            self._select_url(school=self.other_school, year=self.other_year),
            self._select_url(household=self.other_household),
        ):
            with self.subTest(url=url):
                self.assertEqual(
                    client.post(url, HTTP_X_CSRFTOKEN=token).status_code, 404
                )
        self.assertFalse(AidApplicationStudent.objects.exists())

    def test_missing_draft_does_not_create_application_or_selection(self):
        client, token = self._csrf_client()
        self.assertEqual(
            client.post(
                self._select_url(year=self.next_year),
                HTTP_X_CSRFTOKEN=token,
            ).status_code, 404
        )
        self.assertEqual(
            client.get(self._list_url(year=self.next_year)).status_code, 404
        )
        self.assertEqual(AidApplicationStudent.objects.count(), 0)
        self.assertEqual(self.household.aid_applications.count(), 1)

    def test_anonymous_and_unassigned_users_denied(self):
        self.assertEqual(self.client.get(self._list_url()).status_code, 403)
        self.client.force_login(self.unassigned)
        self.assertEqual(self.client.get(self._list_url()).status_code, 404)
        self.assertEqual(self.client.post(self._select_url()).status_code, 404)

    def test_superuser_without_grant_is_denied(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self._list_url()).status_code, 404)
        self.assertEqual(self.client.post(self._select_url()).status_code, 404)

    def test_post_without_csrf_rejected(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.parent)
        self.assertEqual(client.post(self._select_url()).status_code, 403)
        self.assertFalse(AidApplicationStudent.objects.exists())

    def test_revoked_household_grant_blocks_read_and_selection(self):
        client, token = self._csrf_client()
        HouseholdAccess.objects.filter(
            household=self.household, user=self.parent
        ).update(is_active=False)
        self.assertEqual(client.get(self._list_url()).status_code, 404)
        self.assertEqual(
            client.post(self._select_url(), HTTP_X_CSRFTOKEN=token).status_code,
            404,
        )
        self.assertFalse(AidApplicationStudent.objects.exists())

    def test_inactive_identity_or_household_denied(self):
        client, token = self._csrf_client()
        self.household.is_active = False
        self.household.save()
        self.assertEqual(
            client.post(self._select_url(), HTTP_X_CSRFTOKEN=token).status_code,
            404,
        )
        self.household.is_active = True
        self.household.save()
        self.parent.is_active = False
        self.parent.save()
        self.assertEqual(
            client.post(self._select_url(), HTTP_X_CSRFTOKEN=token).status_code,
            403,
        )

    def test_wrong_methods_cannot_create_selection(self):
        self.client.force_login(self.parent)
        for action in (self.client.get, self.client.put, self.client.delete):
            with self.subTest(action=action.__name__):
                self.assertEqual(action(self._select_url()).status_code, 405)
        self.assertFalse(AidApplicationStudent.objects.exists())

    def test_selection_model_rejects_another_household_link(self):
        other_link = HouseholdStudent.objects.get(
            household=self.separate_household, student=self.child
        )
        with self.assertRaises(ValidationError):
            AidApplicationStudent(
                application=self.primary_draft, household_student=other_link
            ).save()
        self.assertFalse(AidApplicationStudent.objects.exists())

    def test_uniqueness_enforced_in_database(self):
        first = select_student_for_draft(**self._args())
        second = select_student_for_draft(**self._args(student=self.sibling))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AidApplicationStudent.objects.filter(pk=second.pk).update(
                    household_student_id=first.household_student_id
                )
        self.assertEqual(AidApplicationStudent.objects.count(), 2)

    def test_household_student_link_cannot_be_deleted_when_selected(self):
        selection = select_student_for_draft(**self._args())
        with self.assertRaises(ProtectedError):
            selection.household_student.delete()

    def test_selected_student_scope_is_required_and_school_bound(self):
        select_student_for_draft(**self._args())
        with self.assertRaises(ValueError):
            AidApplicationStudent.objects.for_school(None)
        self.assertEqual(
            AidApplicationStudent.objects.for_school(self.school.pk).count(), 1
        )
        self.assertEqual(
            AidApplicationStudent.objects.for_school(self.other_school.pk).count(),
            0,
        )

    def test_domain_service_fails_closed_without_household_grant(self):
        with self.assertRaises(Http404):
            select_student_for_draft(
                **self._args(user=self.unassigned)
            )
        with self.assertRaises(Http404):
            selected_student_ids_for_draft(
                user=self.unassigned,
                school_id=self.school.pk,
                household_id=self.household.pk,
                academic_year_id=self.year.pk,
            )

    def test_response_has_identifiers_not_financial_data(self):
        client, token = self._csrf_client()
        payload = client.post(
            self._select_url(), HTTP_X_CSRFTOKEN=token
        ).json()
        self.assertEqual(
            set(payload), {"application_id", "selection_id", "student_id"}
        )
        self.assertNotIn("income", str(payload))
        self.assertNotIn("payment", str(payload))
