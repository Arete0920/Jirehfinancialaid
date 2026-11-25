"""HTTP acceptance for the read-only fictional director assessment."""

from unittest.mock import patch
from uuid import uuid4

from django.db import connection
from django.http import Http404
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from jireh.schools.demo_seed import seed_synthetic_browser_demo
from jireh.schools.models import SchoolStaffAccess

from .models import AidApplication
from .assessment_evidence import EvidenceState
from .services import get_or_create_annual_draft
from .synthetic_assessment import preview_fictional_assessment_evidence


class FictionalAssessmentHTTPTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.demo = seed_synthetic_browser_demo()
        cls.application = get_or_create_annual_draft(
            user=cls.demo["parent"],
            school_id=cls.demo["school_a"].pk,
            household_id=cls.demo["household_a"].pk,
            academic_year_id=cls.demo["year_a"].pk,
        )

    def url(self, scenario="fictional_modest", *, school="a", year="a", application=None):
        return (
            f"/api/v1/schools/{self.demo[f'school_{school}'].pk}/academic-years/"
            f"{self.demo[f'year_{year}'].pk}/aid-applications/"
            f"{application or self.application.pk}/synthetic/assessment/{scenario}/"
        )

    def test_both_scenarios_have_exact_bucket_results_without_database_writes(self):
        self.client.force_login(self.demo["director_a"])
        for scenario, expected_totals, total, hardship_capped in (
            ("fictional_modest", [3200, 0, 0, 1000, 5000], 9200, True),
            ("fictional_moderate", [5467, 0, 0, 7500, 3000], 15967, False),
        ):
            with self.subTest(scenario=scenario):
                with CaptureQueriesContext(connection) as queries:
                    response = self.client.get(self.url(scenario))
                self.assertEqual(response.status_code, 200)
                self.assertIn("no-store", response["Cache-Control"])
                self.assertTrue(queries.captured_queries)
                for query in queries:
                    self.assertTrue(query["sql"].lstrip().upper().startswith("SELECT"))
                result = response.json()
                self.assertEqual(result["scenario_id"], scenario)
                self.assertEqual(result["application_id"], str(self.application.pk))
                self.assertEqual(result["policy_version"], "fictional-director-preview-v1")
                self.assertTrue(result["demo_only"])
                self.assertTrue(result["requires_school_authorization"])
                self.assertIs(type(result["total_recommendation_cents"]), int)
                self.assertEqual(result["total_recommendation_cents"], total)
                self.assertEqual([line["bucket"] for line in result["buckets"]], [
                    "need", "mission", "marketing", "merit", "hardship",
                ])
                amounts = [line["recommendation_cents"] for line in result["buckets"]]
                self.assertTrue(all(type(amount) is int for amount in amounts))
                self.assertEqual(amounts, expected_totals)
                self.assertIs(result["buckets"][-1]["cap_applied"], hardship_capped)
                self.assertNotIn("basis_cents", response.content.decode())
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, AidApplication.STATUS_DRAFT)

    def test_internal_evidence_report_is_deterministic_and_school_scoped(self):
        scope = dict(school_id=self.demo["school_a"].pk, academic_year_id=self.demo["year_a"].pk,
                     application_id=self.application.pk, scenario_id="fictional_modest")
        director = self.demo["director_a"]
        report = preview_fictional_assessment_evidence(user=director, **scope)
        self.assertEqual(report, preview_fictional_assessment_evidence(user=director, **scope))
        self.assertEqual(report.application_id, self.application.pk)
        self.assertEqual((report.evidence_version, report.evidence_revision),
                         ("fictional-fixture-evidence-v1", 1))
        self.assertEqual({row.state for row in report.signals}, {EvidenceState.READY})
        self.assertEqual(len({row.source_id for row in report.signals}), 5)
        self.assertEqual(report.assessment.total_recommendation_cents, 9200)
        with self.assertRaises(Http404):
            preview_fictional_assessment_evidence(user=self.demo["director_b"], **scope)

    def test_only_current_same_school_director_can_read(self):
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        for role in ("parent", "director_b"):
            self.client.force_login(self.demo[role])
            self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.client.force_login(self.demo["director_a"])
        grant = SchoolStaffAccess.objects.get(user=self.demo["director_a"])
        grant.is_active = False
        grant.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_school_year_application_and_scenario_are_scoped(self):
        self.client.force_login(self.demo["director_a"])
        for url in (
            self.url(school="b", year="b"), self.url(year="b"),
            self.url(application=uuid4()), self.url("client-supplied"),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_safe_methods_only_and_no_caller_supplied_parameters(self):
        self.client.force_login(self.demo["director_a"])
        self.assertEqual(self.client.post(self.url()).status_code, 405)
        self.assertEqual(self.client.head(self.url()).status_code, 200)
        self.assertEqual(self.client.get(self.url(), {"amount_cents": 1}).status_code, 400)

    def test_catalog_drift_fails_closed(self):
        self.client.force_login(self.demo["director_a"])
        with patch("pathlib.Path.read_text", return_value="{}"):
            response = self.client.get(self.url())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("recommendation_cents", response.content.decode())

    @override_settings(JIREH_SYNTHETIC_SUBMISSION_ONLY=False)
    def test_preview_fails_closed_when_synthetic_mode_is_disabled(self):
        self.client.force_login(self.demo["director_a"])
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    @override_settings(ROOT_URLCONF="jireh.runtime.urls")
    def test_route_is_absent_from_standalone_runtime(self):
        self.client.force_login(self.demo["director_a"])
        self.assertEqual(self.client.get(self.url()).status_code, 404)
