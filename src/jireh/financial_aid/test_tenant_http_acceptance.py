"""Synthetic, real-session HTTP acceptance for Jireh tenant boundaries.

These routes exist only in disposable test settings. Passing this matrix does
not authorize production routing or establish database read isolation.
"""

import json
from datetime import date

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from jireh.financial_aid.models import AidApplication, AidApplicationStudent, AidAuditEvent
from jireh.financial_aid.services import get_or_create_annual_draft
from jireh.schools.models import (
    AcademicYear, Household, HouseholdAccess, School, SchoolStaffAccess, Student,
)
from jireh.schools.services import link_student_to_household


PASSWORD = "Synthetic-Tenant-Acceptance-2026!"


class CrossTenantHTTPAcceptanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.parent_a = User.objects.create_user(
            username="accept-parent-a", password=PASSWORD,
        )
        cls.separate_parent = User.objects.create_user(
            username="accept-separate-parent", password=PASSWORD,
        )
        cls.parent_b = User.objects.create_user(
            username="accept-parent-b", password=PASSWORD,
        )
        cls.director_a = User.objects.create_user(
            username="accept-director-a", password=PASSWORD,
        )
        cls.director_b = User.objects.create_user(
            username="accept-director-b", password=PASSWORD,
        )
        cls.ungranted_admin = User.objects.create_superuser(
            username="accept-ungranted-admin",
            email="accept-admin@example.invalid",
            password=PASSWORD,
        )
        cls.school_a = School.objects.create(code="accept-a", name="School A")
        cls.school_b = School.objects.create(code="accept-b", name="School B")
        cls.year_a = AcademicYear.objects.create(
            school=cls.school_a, name="2026-27",
            start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
        )
        cls.year_b = AcademicYear.objects.create(
            school=cls.school_b, name="2026-27",
            start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
        )
        cls.house_a = Household.objects.create(
            school=cls.school_a, name="A primary household",
        )
        cls.separate_house = Household.objects.create(
            school=cls.school_a, name="A separate-parent household",
        )
        cls.house_b = Household.objects.create(
            school=cls.school_b, name="B household",
        )
        cls.shared_child = Student.objects.create(
            school=cls.school_a, first_name="Synthetic", last_name="Shared",
        )
        cls.child_b = Student.objects.create(
            school=cls.school_b, first_name="Synthetic", last_name="Other",
        )
        for household, child in (
            (cls.house_a, cls.shared_child),
            (cls.separate_house, cls.shared_child),
            (cls.house_b, cls.child_b),
        ):
            link_student_to_household(
                school_id=household.school_id,
                household_id=household.pk,
                student_id=child.pk,
            )
        for household, parent in (
            (cls.house_a, cls.parent_a),
            (cls.separate_house, cls.separate_parent),
            (cls.house_b, cls.parent_b),
        ):
            HouseholdAccess.objects.create(household=household, user=parent)
        for school, director in (
            (cls.school_a, cls.director_a),
            (cls.school_b, cls.director_b),
        ):
            SchoolStaffAccess.objects.create(
                school=school, user=director,
                role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
            )
        cls.separate_draft = get_or_create_annual_draft(
            user=cls.separate_parent,
            school_id=cls.school_a.pk,
            household_id=cls.separate_house.pk,
            academic_year_id=cls.year_a.pk,
        )
        cls.draft_b = get_or_create_annual_draft(
            user=cls.parent_b,
            school_id=cls.school_b.pk,
            household_id=cls.house_b.pk,
            academic_year_id=cls.year_b.pk,
        )

    def _login(self, user):
        client = Client(enforce_csrf_checks=True)
        login_url = reverse("jireh_test_family_login")
        self.assertEqual(client.get(login_url).status_code, 200)
        csrf = client.cookies["csrftoken"].value
        result = client.post(
            login_url,
            data=json.dumps({"username": user.username, "password": PASSWORD}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {"authenticated": True})
        return client

    def _post(self, client, url, **headers):
        return client.post(
            url, HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
            **headers,
        )

    def _family_routes(self, school, household, year, student):
        identity = {
            "school_id": school.pk, "household_id": household.pk,
        }
        annual = {**identity, "academic_year_id": year.pk}
        return {
            "household": reverse("jireh_household_detail", kwargs=identity),
            "students": reverse("jireh_household_students", kwargs=identity),
            "draft": reverse("jireh_family_annual_draft", kwargs=annual),
            "selected": reverse("jireh_aid_selected_students", kwargs=annual),
            "select": reverse(
                "jireh_aid_select_student",
                kwargs={**annual, "student_id": student.pk},
            ),
        }

    def _staff_route(self, school, year):
        return reverse(
            "jireh_staff_application_index",
            kwargs={"school_id": school.pk, "academic_year_id": year.pk},
        )

    def _assert_all_family_routes_hidden(self, client, routes):
        forged = {"HTTP_X_SCHOOL_ID": str(self.school_b.pk)}
        for name in ("household", "students", "draft", "selected"):
            with self.subTest(method="GET", name=name):
                denied = client.get(routes[name], **forged)
                self.assertEqual(denied.status_code, 404)
                self.assertEqual(denied.json(), {"detail": "Not found."})
        for name in ("draft", "select"):
            with self.subTest(method="POST", name=name):
                denied = self._post(client, routes[name], **forged)
                self.assertEqual(denied.status_code, 404)
                self.assertEqual(denied.json(), {"detail": "Not found."})

    def _counts(self):
        return (
            AidApplication.objects.count(),
            AidApplicationStudent.objects.count(),
            AidAuditEvent.objects.count(),
        )

    def test_real_login_prevents_cross_school_and_shared_child_disclosure(self):
        own = self._family_routes(
            self.school_a, self.house_a, self.year_a, self.shared_child,
        )
        separate = self._family_routes(
            self.school_a, self.separate_house, self.year_a, self.shared_child,
        )
        other = self._family_routes(
            self.school_b, self.house_b, self.year_b, self.child_b,
        )
        parent = self._login(self.parent_a)
        self.assertEqual(parent.get(own["household"]).status_code, 200)
        self.assertEqual(self._post(parent, own["draft"]).status_code, 200)
        self.assertEqual(self._post(parent, own["select"]).status_code, 200)
        self.assertEqual(
            parent.get(own["selected"]).json()["student_ids"],
            [str(self.shared_child.pk)],
        )
        before = self._counts()
        self._assert_all_family_routes_hidden(parent, separate)
        self._assert_all_family_routes_hidden(parent, other)
        self.assertEqual(
            parent.get(self._staff_route(self.school_a, self.year_a)).status_code,
            404,
        )
        self.assertEqual(
            parent.get(self._staff_route(self.school_b, self.year_b)).status_code,
            404,
        )
        # A valid household does not make a foreign academic year valid.
        wrong_year = self._family_routes(
            self.school_a, self.house_a, self.year_b, self.shared_child,
        )
        self.assertEqual(parent.get(wrong_year["draft"]).status_code, 404)
        self.assertEqual(self._post(parent, wrong_year["draft"]).status_code, 404)
        self.assertEqual(parent.get(wrong_year["selected"]).status_code, 404)
        self.assertEqual(self._post(parent, wrong_year["select"]).status_code, 404)
        self.assertEqual(self._counts(), before)

        separated = self._login(self.separate_parent)
        selected = separated.get(separate["selected"])
        self.assertEqual(selected.status_code, 200)
        self.assertEqual(selected.json()["application_id"], str(self.separate_draft.pk))
        self.assertEqual(selected.json()["student_ids"], [])
        self._assert_all_family_routes_hidden(separated, own)

        other_parent = self._login(self.parent_b)
        self.assertEqual(other_parent.get(other["draft"]).status_code, 200)
        self.assertEqual(other_parent.get(other["students"]).status_code, 200)
        self._assert_all_family_routes_hidden(other_parent, own)
        self.assertEqual(self._counts(), before)

    def test_revocation_denies_all_routes_in_an_existing_authenticated_session(self):
        own = self._family_routes(
            self.school_a, self.house_a, self.year_a, self.shared_child,
        )
        parent = self._login(self.parent_a)
        self.assertEqual(self._post(parent, own["draft"]).status_code, 200)
        self.assertEqual(self._post(parent, own["select"]).status_code, 200)
        before = self._counts()
        HouseholdAccess.objects.filter(
            household=self.house_a, user=self.parent_a,
        ).update(is_active=False)
        self._assert_all_family_routes_hidden(parent, own)
        self.assertEqual(self._counts(), before)

        director = self._login(self.director_a)
        staff_url = self._staff_route(self.school_a, self.year_a)
        self.assertEqual(director.get(staff_url).status_code, 200)
        SchoolStaffAccess.objects.filter(
            school=self.school_a, user=self.director_a,
        ).update(is_active=False)
        self.assertEqual(director.get(staff_url).status_code, 404)
        self.assertEqual(
            self._login(self.parent_b).get(
                self._family_routes(
                    self.school_b, self.house_b, self.year_b, self.child_b,
                )["draft"],
            ).status_code,
            200,
        )

    def test_directors_cannot_cross_schools_or_inherit_household_access(self):
        family_a = self._family_routes(
            self.school_a, self.house_a, self.year_a, self.shared_child,
        )
        family_b = self._family_routes(
            self.school_b, self.house_b, self.year_b, self.child_b,
        )
        staff_a = self._staff_route(self.school_a, self.year_a)
        staff_b = self._staff_route(self.school_b, self.year_b)
        for director, allowed, forbidden, family in (
            (self.director_a, staff_a, staff_b, family_a),
            (self.director_b, staff_b, staff_a, family_b),
        ):
            with self.subTest(director=director.username):
                client = self._login(director)
                response = client.get(allowed)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.json()["applications"]), 1)
                self.assertEqual(client.get(forbidden).status_code, 404)
                self._assert_all_family_routes_hidden(client, family)

        admin = self._login(self.ungranted_admin)
        for url in (staff_a, staff_b, family_a["draft"], family_b["draft"]):
            with self.subTest(url=url):
                self.assertEqual(admin.get(url).status_code, 404)
