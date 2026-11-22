"""Synthetic demo rehearsal through real, disposable Django test HTTP sessions.

This suite is NOT a browser UI, live customer flow, or production certification.
No real identity or financial data is used; test databases are discarded.
"""

import json
from datetime import date

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from jireh.financial_aid.models import AidApplication, AidApplicationStudent, AidAuditEvent
from jireh.schools.models import (
    AcademicYear,
    Household,
    HouseholdAccess,
    School,
    SchoolStaffAccess,
    Student,
)
from jireh.schools.services import link_student_to_household


PASSWORD = "Synthetic-Demo-Only-2026!"


class GuidedDemoRehearsalTests(TestCase):
    """A guided proof of the already-implemented, test-only Jireh capabilities."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.parent = User.objects.create_user(
            username="synthetic-demo-parent", password=PASSWORD,
        )
        cls.school_a_director = User.objects.create_user(
            username="synthetic-demo-director-a", password=PASSWORD,
        )
        cls.school_b_director = User.objects.create_user(
            username="synthetic-demo-director-b", password=PASSWORD,
        )
        cls.school_a = School.objects.create(
            code="synthetic-demo-school-a", name="Synthetic School A",
        )
        cls.school_b = School.objects.create(
            code="synthetic-demo-school-b", name="Synthetic School B",
        )
        cls.year_a = AcademicYear.objects.create(
            school=cls.school_a,
            name="2026-27",
            start_date=date(2026, 8, 1),
            end_date=date(2027, 6, 30),
        )
        cls.year_b = AcademicYear.objects.create(
            school=cls.school_b,
            name="2026-27",
            start_date=date(2026, 8, 1),
            end_date=date(2027, 6, 30),
        )
        cls.household_a = Household.objects.create(
            school=cls.school_a, name="Synthetic Household A",
        )
        cls.household_b = Household.objects.create(
            school=cls.school_b, name="Synthetic Household B",
        )
        cls.child_one = Student.objects.create(
            school=cls.school_a, first_name="Sample", last_name="One",
        )
        cls.child_two = Student.objects.create(
            school=cls.school_a, first_name="Sample", last_name="Two",
        )
        cls.child_b = Student.objects.create(
            school=cls.school_b, first_name="Sample", last_name="Other",
        )
        for household, student in (
            (cls.household_a, cls.child_one),
            (cls.household_a, cls.child_two),
            (cls.household_b, cls.child_b),
        ):
            link_student_to_household(
                school_id=household.school_id,
                household_id=household.pk,
                student_id=student.pk,
            )
        HouseholdAccess.objects.create(
            household=cls.household_a, user=cls.parent,
        )
        for school, director in (
            (cls.school_a, cls.school_a_director),
            (cls.school_b, cls.school_b_director),
        ):
            SchoolStaffAccess.objects.create(
                school=school,
                user=director,
                role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
            )

    def _urls(self, school, household, year, student):
        household_scope = {"school_id": school.pk, "household_id": household.pk}
        annual_scope = {**household_scope, "academic_year_id": year.pk}
        return {
            "household": reverse("jireh_household_detail", kwargs=household_scope),
            "students": reverse("jireh_household_students", kwargs=household_scope),
            "draft": reverse("jireh_family_annual_draft", kwargs=annual_scope),
            "selected": reverse("jireh_aid_selected_students", kwargs=annual_scope),
            "select": reverse(
                "jireh_aid_select_student",
                kwargs={**annual_scope, "student_id": student.pk},
            ),
            "staff": reverse(
                "jireh_staff_application_index",
                kwargs={"school_id": school.pk, "academic_year_id": year.pk},
            ),
        }

    def _login(self, user):
        client = Client(enforce_csrf_checks=True)
        login_url = reverse("jireh_test_family_login")
        self.assertEqual(client.get(login_url).status_code, 200)
        response = client.post(
            login_url,
            data=json.dumps({"username": user.username, "password": PASSWORD}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"authenticated": True})
        return client

    def _post(self, client, url, **headers):
        return client.post(
            url,
            HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
            **headers,
        )

    def test_01_family_journey_and_school_director_inventory(self):
        """Synthetic sign-in, create/resume draft, select siblings, staff read."""
        a = self._urls(
            self.school_a, self.household_a, self.year_a, self.child_one,
        )
        family = self._login(self.parent)
        print("DEMO 01: Synthetic parent authenticated in disposable test settings")
        self.assertEqual(family.get(a["household"]).status_code, 200)
        students = family.get(a["students"])
        self.assertEqual(students.status_code, 200)
        self.assertEqual(
            {row["id"] for row in students.json()["students"]},
            {str(self.child_one.pk), str(self.child_two.pk)},
        )
        print("DEMO 02: Household view and two children returned for School A")

        self.assertEqual(family.get(a["draft"]).status_code, 404)
        create = self._post(family, a["draft"])
        self.assertEqual(create.status_code, 200)
        draft_id = create.json()["id"]
        self.assertEqual(
            family.get(a["draft"]).json()["id"], draft_id,
        )
        self.assertEqual(self._post(family, a["draft"]).json()["id"], draft_id)
        self.assertEqual(AidApplication.objects.count(), 1)
        print("DEMO 03: Annual draft created and resumed without duplication")

        for child in (self.child_one, self.child_two):
            chosen = self._urls(
                self.school_a, self.household_a, self.year_a, child,
            )["select"]
            added = self._post(family, chosen)
            self.assertEqual(added.status_code, 200)
            self.assertEqual(added.json()["application_id"], draft_id)
            self.assertEqual(self._post(family, chosen).status_code, 200)
        self.assertEqual(
            set(family.get(a["selected"]).json()["student_ids"]),
            {str(self.child_one.pk), str(self.child_two.pk)},
        )
        self.assertEqual(AidApplicationStudent.objects.count(), 2)
        self.assertEqual(
            AidAuditEvent.objects.filter(application_id=draft_id).count(), 3,
        )
        print("DEMO 04: Two siblings selected; repeat requests remain idempotent")

        self.assertEqual(family.get(a["staff"]).status_code, 404)
        director = self._login(self.school_a_director)
        inventory = director.get(a["staff"])
        self.assertEqual(inventory.status_code, 200)
        self.assertEqual(
            [row["id"] for row in inventory.json()["applications"]],
            [draft_id],
        )
        self.assertEqual(inventory.json()["has_more"], False)
        print("DEMO 05: School A director sees the draft; parent cannot read staff queue")
        print("DEMO LIMIT: No financial questions, uploads, submitted status, awards or payment")

    def test_02_tenant_boundary_csrf_and_revocation(self):
        """Show explicit negative controls with the same synthetic identities."""
        a = self._urls(
            self.school_a, self.household_a, self.year_a, self.child_one,
        )
        b = self._urls(
            self.school_b, self.household_b, self.year_b, self.child_b,
        )
        family = self._login(self.parent)
        self.assertEqual(self._post(family, a["draft"]).status_code, 200)
        before = AidApplication.objects.count()
        for key in ("household", "students", "draft", "selected"):
            with self.subTest(route=key):
                self.assertEqual(
                    family.get(b[key], HTTP_X_SCHOOL_ID=str(self.school_b.pk)).status_code,
                    404,
                )
        for key in ("draft", "select"):
            with self.subTest(mutation=key):
                self.assertEqual(
                    self._post(
                        family, b[key], HTTP_X_SCHOOL_ID=str(self.school_b.pk),
                    ).status_code,
                    404,
                )
        self.assertEqual(family.get(b["staff"]).status_code, 404)
        self.assertEqual(AidApplication.objects.count(), before)
        print("DEMO 06: Cross-school reads and mutations denied despite forged school header")

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.parent)
        self.assertEqual(csrf_client.post(a["select"]).status_code, 403)
        self.assertFalse(AidApplicationStudent.objects.exists())
        print("DEMO 07: State-changing request without CSRF token denied")

        HouseholdAccess.objects.filter(
            household=self.household_a, user=self.parent,
        ).update(is_active=False)
        self.assertEqual(family.get(a["household"]).status_code, 404)
        self.assertEqual(family.get(a["draft"]).status_code, 404)
        self.assertEqual(self._post(family, a["select"]).status_code, 404)
        self.assertEqual(AidApplication.objects.count(), before)
        print("DEMO 08: Revoked household grant blocks existing authenticated session")

        director_b = self._login(self.school_b_director)
        self.assertEqual(director_b.get(a["staff"]).status_code, 404)
        self.assertEqual(director_b.get(b["staff"]).status_code, 200)
        print("DEMO 09: Director for School B cannot see School A inventory")
