"""Fail-closed HTTP contract for the fictional Arete operations overview."""
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import Resolver404, resolve

from jireh.schools.demo_preparation_jobs import advance_synthetic_preparation
from jireh.schools.demo_seed import seed_synthetic_browser_demo
from jireh.schools.demo_setup_intents import record_synthetic_setup_intent
from jireh.schools.models import (
    AcademicYear, School, SchoolPreparationEvent, SchoolSetupIntent, SchoolStaffAccess,
)


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

    def test_empty_preparation_summary_does_not_claim_success(self):
        self.client.force_login(self.records["operator"])
        page = self.client.get(self.url())
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "No preparation receipts have been recorded.")
        self.assertEqual(page.context["preparation_total"], 0)
        self.assertEqual(sum(page.context["preparation_counts"].values()), 0)

    @override_settings(
        JIREH_SYNTHETIC_SETUP_INTENT_ONLY=True,
        JIREH_SYNTHETIC_PREPARATION_JOB_ONLY=True,
    )
    def test_saved_preparation_status_is_owned_read_only_and_current(self):
        operator = self.records["operator"]

        def receipt(code):
            payload = {
                "code": code, "name": "Fictional Preparation Academy",
                "timezone": "America/New_York", "idempotency_key": str(uuid4()),
            }
            saved = record_synthetic_setup_intent(operator=operator, payload=payload)
            return payload, saved

        def advance(payload, action):
            return advance_synthetic_preparation(
                operator=operator, payload=payload, command=action, request_key=uuid4(),
            )

        _, received = receipt("not-queued")
        queued, _ = receipt("queued-school")
        advance(queued, "QUEUE")
        prepared, _ = receipt("prepared-school")
        advance(prepared, "QUEUE")
        advance(prepared, "RUN")
        failed, _ = receipt(self.records["school_a"].code)
        advance(failed, "QUEUE")
        advance(failed, "RUN")
        retry, _ = receipt("retry-school")
        existing = School.objects.create(
            code=retry["code"], name="Fictional conflict", is_active=False,
        )
        advance(retry, "QUEUE")
        advance(retry, "RUN")
        existing.delete()
        advance(retry, "RETRY")
        other = get_user_model().objects.create_user(username="other-operator")
        foreign = SchoolSetupIntent.objects.create(
            proposed_by=other, candidate_digest="a" * 64, idempotency_key=uuid4(),
        )
        self.client.force_login(operator)
        events_before = SchoolPreparationEvent.objects.count()
        with CaptureQueriesContext(connection) as queries:
            page = self.client.get(self.url())
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["preparation_counts"], {
            "RECEIVED": 1, "QUEUED": 1, "REQUEUED": 1, "PREPARED": 1, "FAILED": 1,
        })
        self.assertEqual(page.context["preparation_total"], 5)
        self.assertTrue(all(q["sql"].lstrip().upper().startswith("SELECT") for q in queries))
        self.assertEqual(SchoolPreparationEvent.objects.count(), events_before)
        self.assertEqual(School.objects.count(), 2)
        for private_value in (
            str(received.pk), str(received.idempotency_key), received.candidate_digest,
            str(foreign.pk), str(foreign.idempotency_key), foreign.candidate_digest,
        ):
            self.assertNotContains(page, private_value)
        advance(queued, "RUN")
        page = self.client.get(self.url())
        self.assertEqual(page.context["preparation_counts"]["QUEUED"], 0)
        self.assertEqual(page.context["preparation_counts"]["PREPARED"], 2)

    def test_corrupt_preparation_history_fails_closed(self):
        operator = self.records["operator"]
        receipt = SchoolSetupIntent.objects.create(
            proposed_by=operator, candidate_digest="b" * 64, idempotency_key=uuid4(),
        )
        SchoolPreparationEvent.objects.create(
            intent=receipt, actor=operator, request_key=uuid4(),
            sequence=1, attempt=1, action="STARTED",
        )
        self.client.force_login(operator)
        page = self.client.get(self.url())
        self.assertEqual(page.status_code, 503)
        self.assertNotIn(str(receipt.pk), page.content.decode())
        self.assertNotIn("STARTED", page.content.decode())
        self.assertNotIn("Synthetic Christian Academy", page.content.decode())

    def test_preparation_database_failure_is_generic(self):
        self.client.force_login(self.records["operator"])
        with patch(
            "jireh.schools.demo_platform_operations._saved_preparation_counts",
            side_effect=DatabaseError("private setup data"),
        ):
            page = self.client.get(self.url())
        self.assertEqual(page.status_code, 503)
        self.assertNotIn("private setup data", page.content.decode())

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
