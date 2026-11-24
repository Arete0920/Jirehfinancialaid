"""HTTP acceptance of the fixed-fictional family financial questionnaire preview."""

from unittest.mock import patch
from uuid import uuid4

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from jireh.schools.demo_seed import seed_synthetic_browser_demo
from jireh.schools.models import HouseholdAccess

from .models import AidApplication, AidAuditEvent
from .services import get_or_create_annual_draft


class FictionalFamilyQuestionnaireHTTPTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.demo = seed_synthetic_browser_demo()
        cls.application = get_or_create_annual_draft(
            user=cls.demo["parent"],
            school_id=cls.demo["school_a"].pk,
            household_id=cls.demo["household_a"].pk,
            academic_year_id=cls.demo["year_a"].pk,
        )

    def url(self, scenario="fictional_modest", *, school="a", year="a", household=None):
        return (
            f"/api/v1/schools/{self.demo[f'school_{school}'].pk}/households/"
            f"{household or self.demo['household_a'].pk}/academic-years/"
            f"{self.demo[f'year_{year}'].pk}/aid-application/draft/"
            f"synthetic/questionnaire/{scenario}/"
        )

    def test_fixed_scenarios_are_value_free_read_only_and_incomplete(self):
        self.client.force_login(self.demo["parent"])
        counts = (AidApplication.objects.count(), AidAuditEvent.objects.count())
        for scenario in ("fictional_modest", "fictional_moderate"):
            with self.subTest(scenario=scenario):
                with CaptureQueriesContext(connection) as queries:
                    response = self.client.get(self.url(scenario))
                self.assertEqual(response.status_code, 200)
                self.assertIn("no-store", response["Cache-Control"])
                self.assertTrue(queries.captured_queries)
                for query in queries:
                    self.assertTrue(query["sql"].lstrip().upper().startswith("SELECT"))
                data = response.json()
                self.assertEqual(data, {
                    "scenario_id": scenario,
                    "demo_only": True,
                    "validated_candidate_sections": [
                        "income", "assets", "liabilities",
                    ],
                    "full_questionnaire_complete": False,
                    "financial_answers_stored": False,
                    "consent_captured": False,
                    "assessment_or_award_performed": False,
                    "school_id": str(self.demo["school_a"].pk),
                    "household_id": str(self.demo["household_a"].pk),
                    "academic_year_id": str(self.demo["year_a"].pk),
                    "application_id": str(self.application.pk),
                })
                for private_value in ("4800000", "8200000", "200000", "11111111"):
                    self.assertNotIn(private_value, response.content.decode())
        self.assertEqual(
            (AidApplication.objects.count(), AidAuditEvent.objects.count()), counts
        )
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, AidApplication.STATUS_DRAFT)

    def test_unauthorized_scopes_denied_without_disclosing_fixtures(self):
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        for actor in ("director_a", "director_b"):
            self.client.force_login(self.demo[actor])
            self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.client.force_login(self.demo["parent"])
        for path in (
            self.url(school="b", year="b", household=self.demo["household_b"].pk),
            self.url(year="b"),
            self.url(household=self.demo["household_b"].pk),
            self.url(household=uuid4()),
            self.url("unapproved-financial-policy"),
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)
                self.assertNotIn("amount_cents", self.client.get(path).content.decode())

    def test_revocation_and_runtime_disabled_are_fail_closed(self):
        self.client.force_login(self.demo["parent"])
        grant = HouseholdAccess.objects.get(
            household=self.demo["household_a"], user=self.demo["parent"],
        )
        grant.is_active = False
        grant.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        grant.is_active = True
        grant.save(update_fields=["is_active"])
        with override_settings(JIREH_SYNTHETIC_SUBMISSION_ONLY=False):
            self.assertEqual(self.client.get(self.url()).status_code, 403)
        with override_settings(ROOT_URLCONF="jireh.runtime.urls"):
            self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_no_write_methods_or_untrusted_financial_parameters(self):
        self.client.force_login(self.demo["parent"])
        self.assertEqual(self.client.post(self.url()).status_code, 405)
        self.assertEqual(self.client.head(self.url()).status_code, 200)
        self.assertEqual(
            self.client.get(self.url(), {"income_cents": "100000"}).status_code, 400
        )

    def test_catalog_unavailable_fails_closed(self):
        self.client.force_login(self.demo["parent"])
        with patch("pathlib.Path.read_text", return_value="{}"):
            response = self.client.get(self.url())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("income", response.content.decode())
