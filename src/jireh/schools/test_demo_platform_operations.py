"""Fail-closed HTTP contract for the fictional Arete operations overview."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import Resolver404, resolve

from jireh.schools.demo_seed import seed_synthetic_browser_demo
from jireh.schools.models import AcademicYear, School, SchoolStaffAccess


DEMO_TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [], "APP_DIRS": True, "OPTIONS": {},
}]


@override_settings(
    ROOT_URLCONF="jireh.schools.demo_urls",
    TEMPLATES=DEMO_TEMPLATES,
    JIREH_SYNTHETIC_SUBMISSION_ONLY=True,
)
class LocalOperationsPreviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.records = seed_synthetic_browser_demo()

    @staticmethod
    def url():
        return "/local-demo/platform-operations/"

    def test_only_explicit_fictional_staff_operator_can_read_saved_inventory(self):
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        for role in ("parent", "director_a", "director_b"):
            self.client.force_login(self.records[role])
            self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.client.force_login(self.records["operator"])
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
        self.assertTrue(queries.captured_queries)
        self.assertTrue(all(q["sql"].lstrip().upper().startswith("SELECT") for q in queries))
        html = response.content.decode()
        for value in (
            "School readiness overview", "Synthetic Christian Academy",
            "Synthetic School B", "2026-27", "Fictional seed only",
            "Not configured", "Not a provisioning system",
        ):
            self.assertIn(value, html)
        self.assertNotIn("Sample Family", html)
        self.assertNotIn("Unrelated Family", html)
        self.assertNotIn("Jordan Sample", html)

    def test_authorization_is_not_generic_staff_or_superuser(self):
        other = get_user_model().objects.create_user(
            username="other-staff", password="not-a-secret", is_staff=True
        )
        self.client.force_login(other)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        operator = self.records["operator"]
        operator.is_staff = False
        operator.save(update_fields=["is_staff"])
        self.client.force_login(operator)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        operator.is_staff = True
        operator.is_superuser = True
        operator.save(update_fields=["is_staff", "is_superuser"])
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_no_query_override_or_mutating_method(self):
        self.client.force_login(self.records["operator"])
        for query in ("?school_id=other", "?include_financials=1"):
            self.assertEqual(self.client.get(self.url() + query).status_code, 400)
        self.assertEqual(self.client.post(self.url()).status_code, 405)
        self.assertEqual(self.client.put(self.url()).status_code, 405)

    def test_denies_runtime_or_synthetic_flag_disabled(self):
        self.client.force_login(self.records["operator"])
        with override_settings(JIREH_SYNTHETIC_SUBMISSION_ONLY=False):
            self.assertEqual(self.client.get(self.url()).status_code, 403)
        with override_settings(ROOT_URLCONF="jireh.runtime.urls"):
            with self.assertRaises(Resolver404):
                resolve(self.url())

    def test_unexpected_school_and_missing_year_fail_closed(self):
        self.client.force_login(self.records["operator"])
        School.objects.create(code="unexpected-school", name="Hidden Test Tenant")
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("Hidden Test Tenant", response.content.decode())
        School.objects.filter(code="unexpected-school").delete()
        AcademicYear.objects.filter(school=self.records["school_b"]).delete()
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("Synthetic Christian Academy", response.content.decode())

    def test_director_revocation_changes_saved_count(self):
        self.client.force_login(self.records["operator"])
        page = self.client.get(self.url())
        self.assertEqual(page.status_code, 200)
        self.assertIn("<td>1</td>", page.content.decode())
        grant = SchoolStaffAccess.objects.get(
            school=self.records["school_a"], user=self.records["director_a"]
        )
        grant.is_active = False
        grant.save(update_fields=["is_active"])
        page = self.client.get(self.url())
        self.assertEqual(page.status_code, 200)
        self.assertIn("<td>0</td>", page.content.decode())

    def test_operational_failure_is_generic(self):
        self.client.force_login(self.records["operator"])
        with patch("jireh.schools.demo_platform_operations._saved_school_inventory",
                   side_effect=__import__("jireh.schools.demo_platform_operations",
                                           fromlist=["OperationsPreviewIntegrityError"]).OperationsPreviewIntegrityError("private internal detail")):
            page = self.client.get(self.url())
        self.assertEqual(page.status_code, 503)
        self.assertNotIn("private internal detail", page.content.decode())
