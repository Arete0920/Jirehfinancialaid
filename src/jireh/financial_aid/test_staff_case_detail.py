"""Read-only, grant-checked officer case inspection in disposable routing only."""
from datetime import date
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from jireh.financial_aid.models import AidApplication, AidApplicationStudent, AidAuditEvent
from jireh.financial_aid.services import get_or_create_annual_draft, select_student_for_draft
from jireh.schools.models import (
    AcademicYear, Household, HouseholdAccess, School, SchoolStaffAccess, Student,
)
from jireh.schools.services import link_student_to_household


class OfficerCaseDetailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.parent = User.objects.create_user(username="case-parent")
        cls.director_a = User.objects.create_user(username="case-director-a")
        cls.director_b = User.objects.create_user(username="case-director-b")
        cls.ungranted_admin = User.objects.create_superuser(
            username="case-admin", email="case-admin@example.invalid", password="synthetic-only"
        )
        cls.school_a = School.objects.create(code="case-school-a", name="School A")
        cls.school_b = School.objects.create(code="case-school-b", name="School B")
        cls.year_a = AcademicYear.objects.create(
            school=cls.school_a, name="2026-27", start_date=date(2026, 8, 1),
            end_date=date(2027, 6, 30),
        )
        cls.year_b = AcademicYear.objects.create(
            school=cls.school_b, name="2026-27", start_date=date(2026, 8, 1),
            end_date=date(2027, 6, 30),
        )
        cls.household = Household.objects.create(school=cls.school_a, name="Case household")
        HouseholdAccess.objects.create(household=cls.household, user=cls.parent)
        for school, director in ((cls.school_a, cls.director_a), (cls.school_b, cls.director_b)):
            SchoolStaffAccess.objects.create(
                school=school, user=director, role=SchoolStaffAccess.ROLE_AID_DIRECTOR
            )
        cls.draft = get_or_create_annual_draft(
            user=cls.parent, school_id=cls.school_a.pk,
            household_id=cls.household.pk, academic_year_id=cls.year_a.pk,
        )
        cls.children = []
        for i in range(2):
            student = Student.objects.create(
                school=cls.school_a, first_name=f"Synthetic{i}", last_name="Child"
            )
            cls.children.append(student)
            link_student_to_household(
                school_id=cls.school_a.pk, household_id=cls.household.pk,
                student_id=student.pk,
            )
            select_student_for_draft(
                user=cls.parent, school_id=cls.school_a.pk,
                household_id=cls.household.pk,
                academic_year_id=cls.year_a.pk, student_id=student.pk,
            )

    def detail_url(self, school=None, year=None, application_id=None):
        return reverse(
            "jireh_staff_application_detail",
            kwargs={
                "school_id": school or self.school_a.pk,
                "academic_year_id": year or self.year_a.pk,
                "application_id": application_id or self.draft.pk,
            },
        )

    def test_director_sees_only_authorized_draft_and_child_uuid_summary(self):
        self.client.force_login(self.director_a)
        response = self.client.get(self.detail_url())
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            set(data),
            {"school_id", "academic_year_id", "application_id", "status",
             "selected_student_count", "selected_student_ids"},
        )
        self.assertEqual(data["school_id"], str(self.school_a.pk))
        self.assertEqual(data["academic_year_id"], str(self.year_a.pk))
        self.assertEqual(data["application_id"], str(self.draft.pk))
        self.assertEqual(data["status"], "DRAFT")
        self.assertEqual(data["selected_student_count"], 2)
        self.assertEqual(
            set(data["selected_student_ids"]),
            {str(child.pk) for child in self.children},
        )
        self.assertIn("no-store", response["Cache-Control"].lower())
        self.assertNotIn(self.household.name, response.content.decode())
        self.assertNotIn("income", response.content.decode().lower())

    def test_anonymous_parent_and_other_director_are_denied(self):
        self.assertEqual(self.client.get(self.detail_url()).status_code, 403)
        for user in (self.parent, self.director_b, self.ungranted_admin):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                response = self.client.get(self.detail_url())
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json(), {"detail": "Not found."})

    def test_wrong_school_year_and_case_id_do_not_disclose_data(self):
        self.client.force_login(self.director_a)
        for url in (
            self.detail_url(school=self.school_b.pk),
            self.detail_url(year=self.year_b.pk),
            self.detail_url(application_id=uuid4()),
        ):
            with self.subTest(url=url):
                response = self.client.get(url, HTTP_X_SCHOOL_ID=str(self.school_a.pk))
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json(), {"detail": "Not found."})

    def test_revoked_director_grant_immediately_removes_case_access(self):
        self.client.force_login(self.director_a)
        self.assertEqual(self.client.get(self.detail_url()).status_code, 200)
        SchoolStaffAccess.objects.filter(
            school=self.school_a, user=self.director_a
        ).update(is_active=False)
        self.assertEqual(self.client.get(self.detail_url()).status_code, 404)

    def test_read_only_methods_cannot_mutate_financial_records(self):
        self.client.force_login(self.director_a)
        before = (
            AidApplication.objects.count(), AidApplicationStudent.objects.count(),
            AidAuditEvent.objects.count(),
        )
        self.assertEqual(self.client.head(self.detail_url()).status_code, 200)
        for method in (self.client.post, self.client.put, self.client.delete):
            with self.subTest(method=method.__name__):
                self.assertEqual(method(self.detail_url()).status_code, 405)
        self.assertEqual(
            (
                AidApplication.objects.count(), AidApplicationStudent.objects.count(),
                AidAuditEvent.objects.count(),
            ), before,
        )
