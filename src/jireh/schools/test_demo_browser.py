"""HTTP acceptance for the synthetic, loopback-only browser demonstration.

No production routing or real user data is involved.
"""

import json

from django.test import Client, TestCase, override_settings
from django.urls import resolve, reverse

from jireh.financial_aid.models import AidApplication, AidApplicationStudent
from jireh.schools.demo_seed import (
    DEMO_DIRECTOR_A,
    DEMO_DIRECTOR_B,
    DEMO_PARENT,
    DEMO_PASSWORD,
    seed_synthetic_browser_demo,
)


@override_settings(
    ROOT_URLCONF="jireh.schools.demo_urls",
    TEMPLATES=[
        {
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "DIRS": [],
            "APP_DIRS": True,
            "OPTIONS": {},
        }
    ],
)
class SyntheticBrowserDemoHTTPTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fixture = seed_synthetic_browser_demo()

    def _login(self, role):
        client = Client(enforce_csrf_checks=True)
        login_url = reverse("jireh_test_family_login")
        self.assertEqual(client.get(login_url).status_code, 200)
        result = client.post(
            login_url,
            data=json.dumps({"username": role, "password": DEMO_PASSWORD}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        )
        self.assertEqual(result.status_code, 200)
        return client

    def _scope(self, client):
        response = client.get(reverse("jireh_local_demo_config"))
        self.assertEqual(response.status_code, 200)
        return response.json()

    @staticmethod
    def _draft_url(school):
        return reverse(
            "jireh_family_annual_draft",
            kwargs={
                "school_id": school["id"],
                "household_id": school["household_id"],
                "academic_year_id": school["year_id"],
            },
        )

    @staticmethod
    def _staff_url(school):
        return reverse(
            "jireh_staff_application_index",
            kwargs={
                "school_id": school["id"],
                "academic_year_id": school["year_id"],
            },
        )

    def test_browser_page_is_static_with_demo_only_warning(self):
        page = self.client.get(reverse("jireh_local_demo"))
        self.assertEqual(page.status_code, 200)
        html = page.content.decode()
        for expected in (
            "LOCAL SYNTHETIC DEMO",
            "NOT LIVE",
            "Family applicant",
            "Create / resume annual draft",
            "Select child",
            "Verify School B access is denied",
            "No real data is used",
        ):
            self.assertIn(expected, html)
        self.assertEqual(page["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'none'", page["Content-Security-Policy"])
        self.assertIn("no-store", page["Cache-Control"].lower())
        self.assertEqual(resolve("/local-demo/").url_name, "jireh_local_demo")

    def test_configuration_requires_authenticated_synthetic_persona(self):
        target = reverse("jireh_local_demo_config")
        self.assertEqual(self.client.get(target).status_code, 403)
        client = self._login(DEMO_PARENT)
        conf = self._scope(client)
        self.assertEqual(conf["persona"], DEMO_PARENT)
        self.assertEqual(conf["school_a"]["name"], "Synthetic Christian Academy")
        self.assertNotEqual(conf["school_a"]["id"], conf["school_b"]["id"])

    def test_real_session_family_and_director_browser_endpoints(self):
        family = self._login(DEMO_PARENT)
        conf = self._scope(family)
        a = conf["school_a"]
        b = conf["school_b"]
        a_url = self._draft_url(a)
        b_url = self._draft_url(b)
        household_url = reverse(
            "jireh_household_detail",
            kwargs={"school_id": a["id"], "household_id": a["household_id"]},
        )
        student_url = reverse(
            "jireh_household_students",
            kwargs={"school_id": a["id"], "household_id": a["household_id"]},
        )
        self.assertEqual(family.get(household_url).status_code, 200)
        students = family.get(student_url)
        self.assertEqual(students.status_code, 200)
        self.assertEqual(len(students.json()["students"]), 2)
        self.assertEqual(family.get(a_url).status_code, 404)
        self.assertEqual(family.get(b_url).status_code, 404)
        token = family.cookies["csrftoken"].value
        draft = family.post(a_url, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(draft.status_code, 200)
        self.assertEqual(family.post(a_url, HTTP_X_CSRFTOKEN=token).json(), draft.json())
        self.assertEqual(AidApplication.objects.count(), 1)

        for student in students.json()["students"]:
            select_url = reverse(
                "jireh_aid_select_student",
                kwargs={
                    "school_id": a["id"],
                    "household_id": a["household_id"],
                    "academic_year_id": a["year_id"],
                    "student_id": student["id"],
                },
            )
            self.assertEqual(
                family.post(select_url, HTTP_X_CSRFTOKEN=token).status_code, 200,
            )
        self.assertEqual(AidApplicationStudent.objects.count(), 2)
        self.assertEqual(
            family.post(b_url, HTTP_X_CSRFTOKEN=token).status_code, 404,
        )
        self.assertEqual(family.post(a_url).status_code, 403)

        staff_a = self._staff_url(a)
        staff_b = self._staff_url(b)
        self.assertEqual(family.get(staff_a).status_code, 404)
        da = self._login(DEMO_DIRECTOR_A)
        db = self._login(DEMO_DIRECTOR_B)
        self.assertEqual(len(da.get(staff_a).json()["applications"]), 1)
        self.assertEqual(da.get(staff_b).status_code, 404)
        self.assertEqual(db.get(staff_a).status_code, 404)
        self.assertEqual(db.get(staff_b).status_code, 200)

    def test_switching_personas_requires_separate_login_sessions(self):
        parent = self._login(DEMO_PARENT)
        director = self._login(DEMO_DIRECTOR_A)
        self.assertEqual(self._scope(parent)["persona"], DEMO_PARENT)
        self.assertEqual(self._scope(director)["persona"], DEMO_DIRECTOR_A)
        self.assertEqual(
            parent.post(
                reverse("jireh_test_family_logout"),
                HTTP_X_CSRFTOKEN=parent.cookies["csrftoken"].value,
            ).status_code,
            200,
        )
        self.assertEqual(parent.get(reverse("jireh_local_demo_config")).status_code, 403)
        self.assertEqual(self._scope(director)["persona"], DEMO_DIRECTOR_A)
