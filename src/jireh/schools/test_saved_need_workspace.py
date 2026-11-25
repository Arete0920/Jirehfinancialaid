"""Actual saved-evidence director HTML acceptance, not fixed scenario arithmetic."""
import copy
import json
import secrets
from pathlib import Path

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from jireh.financial_aid.models import AidApplication, SyntheticAidOffer, SyntheticAidSubmission
from jireh.financial_aid.services import get_or_create_annual_draft, select_student_for_draft
from jireh.financial_aid.synthetic_questionnaire_storage import save_fictional_questionnaire
from .demo_seed import seed_synthetic_browser_demo
from .saved_need_workspace import configure_saved_need_fixture
from .workspace_questionnaire import fictional_questionnaire_policy


@override_settings(
    ROOT_URLCONF="jireh.schools.customer_workspace_urls",
    JIREH_CUSTOMER_WORKSPACE_ACCEPTANCE=True,
    JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE=True,
    JIREH_SYNTHETIC_QUESTIONNAIRE_KEY=secrets.token_bytes(32),
    TEMPLATES=[{"BACKEND": "django.template.backends.django.DjangoTemplates",
                "DIRS": [], "APP_DIRS": True, "OPTIONS": {}}],
)
class SavedNeedWorkspaceTests(TestCase):
    def setUp(self):
        self.demo = seed_synthetic_browser_demo()
        self.fixture = configure_saved_need_fixture(self.demo)
        self.scope = dict(user=self.demo["parent"], school_id=self.fixture.school_id,
                          household_id=self.fixture.household_id,
                          academic_year_id=self.fixture.academic_year_id)
        self.draft = get_or_create_annual_draft(**self.scope)
        for student_id, _ in self.fixture.grades:
            select_student_for_draft(**self.scope, student_id=student_id)
        self.policy, _ = fictional_questionnaire_policy(self.draft)
        member = self.policy.member_ids[0]
        self.answers = {
            "income": [{"category": "EMPLOYMENT", "amount": 4_000_000,
                        "period_start": "2026-01-01", "period_end": "2026-12-31", "contributor_id": member}],
            "assets": [{"category": "CASH", "balance": 0, "as_of_date": "2026-06-30", "owner_member_id": member}],
            "liabilities": [{"category": "MORTGAGE", "balance": 0, "as_of_date": "2026-06-30",
                             "responsible_member_id": member}],
            "expenses": [{"category": "HOUSING", "amount": 20_000,
                          "period_start": "2026-01-01", "period_end": "2026-01-31"}],
        }
        self.catalog = json.loads((Path(__file__).resolve().parents[3] / "docs" /
                                   "questionnaire_v1_field_catalog.json").read_text(encoding="utf-8"))
        self.url = reverse("jireh_workspace_case", args=(
            self.fixture.school_id, self.fixture.academic_year_id, self.draft.pk,
        ))

    def save(self, revision, answers):
        from django.conf import settings
        save_fictional_questionnaire(**self.scope, expected_revision=revision,
                                     answers=answers, catalog=self.catalog, policy=self.policy,
                                     key=settings.JIREH_SYNTHETIC_QUESTIONNAIRE_KEY)

    def get_case(self, role="director_a"):
        client = Client()
        client.force_login(self.demo[role])
        return client.get(self.url, secure=True)

    def test_saved_evidence_changes_visible_need_and_remains_nonbinding(self):
        with self.settings(JIREH_SAVED_NEED_FIXTURE=self.fixture):
            self.assertContains(self.get_case(), "Saved-evidence calculation unavailable.")
            self.save(0, self.answers)
            first = self.get_case()
            self.assertContains(first, 'id="saved-need-unmet">$13,959.00</strong>')
            self.assertContains(first, "Questionnaire revision 1")
            self.assertNotContains(first, self.policy.member_ids[0])
            self.assertNotContains(first, "4000000")
            changed = copy.deepcopy(self.answers)
            changed["income"][0]["amount"] = 5_000_000
            self.save(1, changed)
            next_page = self.get_case()
            self.assertContains(next_page, 'id="saved-need-unmet">$8,959.00</strong>')
            self.assertContains(next_page, "Questionnaire revision 2")
            self.assertContains(next_page, "School plan revision 1")
            self.assertNotContains(next_page, "$13,959.00")
            partial = copy.deepcopy(changed)
            partial["income"][0]["period_end"] = "2026-06-30"
            self.save(2, partial)
            unavailable = self.get_case()
            self.assertContains(unavailable, "Saved-evidence calculation unavailable.")
            self.assertNotContains(unavailable, 'id="saved-need-unmet"')
            for role in ("parent", "director_b", "operator"):
                self.assertEqual(self.get_case(role).status_code, 404)
        self.assertFalse(SyntheticAidOffer.objects.exists())
        self.assertFalse(SyntheticAidSubmission.objects.exists())
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AidApplication.STATUS_DRAFT)

    def test_context_is_explicit_and_contributor_hold_prevents_calculation(self):
        from unittest.mock import patch

        self.save(0, self.answers)
        self.assertNotContains(self.get_case(), "Saved-evidence fictional tuition need")
        with self.settings(JIREH_SAVED_NEED_FIXTURE=self.fixture):
            with patch("jireh.schools.saved_need_workspace.contributor_review_pending", return_value=True):
                self.assertContains(self.get_case(), "Saved-evidence calculation unavailable.")
                self.assertNotContains(self.get_case(), 'id="saved-need-unmet"')
            with self.settings(JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE=False):
                self.assertContains(self.get_case(), "Saved-evidence calculation unavailable.")
            with self.settings(ROOT_URLCONF="jireh.runtime.urls"):
                self.assertEqual(self.get_case().status_code, 404)


    def test_revision_bound_projection_is_explicit_and_never_allocates_funds(self):
        from dataclasses import replace
        from jireh.financial_aid.annual_school_plan import FICTIONAL_15145_PLAN
        from jireh.financial_aid.school_plan_revisions import record_fictional_school_plan

        self.save(0, self.answers)
        url = reverse("jireh_workspace_case_projection", args=(
            self.fixture.school_id, self.fixture.academic_year_id, self.draft.pk,
        ))
        data = {"questionnaire_revision": "1", "plan_revision": "1",
                "committed": "10000.00", "proposed": "2500.00"}
        with self.settings(JIREH_SAVED_NEED_FIXTURE=self.fixture):
            director = Client(enforce_csrf_checks=True)
            director.force_login(self.demo["director_a"])
            page = director.get(self.url, secure=True)
            self.assertContains(page, "Project fictional need aid")
            self.assertEqual(page["Referrer-Policy"], "same-origin")
            headers = {"HTTP_X_CSRFTOKEN": director.cookies["csrftoken"].value,
                       "HTTP_REFERER": "https://testserver" + self.url}
            self.assertEqual(director.get(url, secure=True).status_code, 405)
            self.assertEqual(director.post(url, data, secure=True).status_code, 403)
            for origin in ("null", "https://untrusted.example"):
                denied = director.post(url, data, secure=True, HTTP_ORIGIN=origin, **headers)
                self.assertEqual(denied.status_code, 403)
            native_post = director.post(
                url, {**data, "csrfmiddlewaretoken": director.cookies["csrftoken"].value},
                secure=True, HTTP_ORIGIN="https://testserver",
            )
            self.assertContains(native_post, 'id="projection-household-balance">$22,325.00</strong>')
            def post(values):
                return director.post(url, values, secure=True, **headers)
            response = post(data)
            self.assertContains(response, 'id="projection-household-balance">$22,325.00</strong>')
            self.assertContains(response, 'id="projection-remaining-budget">$237,500.00</strong>')
            self.assertContains(response, "No funds have been allocated.")
            self.assertIn("no-store", response["Cache-Control"])
            for invalid in ({"proposed": "-1"}, {"proposed": "1e3"}, {"committed": "1.001"},
                            {"plan_revision": "0"}, {"unexpected": "1"}, {"proposed": ["1", "2"]}):
                self.assertEqual(post({**data, **invalid}).status_code, 400)
            for invalid in ({"proposed": "13959.01"}, {"committed": "249000.00"},
                            {"questionnaire_revision": "2"}, {"plan_revision": "2"}):
                denied = post({**data, **invalid})
                self.assertContains(denied, "Projection unavailable.", status_code=409)
                self.assertNotContains(denied, 'id="projection-remaining-budget"', status_code=409)
            from unittest.mock import patch
            with patch("jireh.schools.saved_need_workspace.contributor_review_pending", return_value=True):
                self.assertEqual(post(data).status_code, 409)
            changed = copy.deepcopy(self.answers)
            changed["income"][0]["amount"] = 5_000_000
            self.save(1, changed)
            self.assertEqual(post(data).status_code, 409)
            updated = {**data, "questionnaire_revision": "2"}
            self.assertEqual(post(updated).status_code, 200)
            record_fictional_school_plan(
                user=self.demo["director_a"], school_id=self.fixture.school_id,
                academic_year_id=self.fixture.academic_year_id,
                plan=replace(FICTIONAL_15145_PLAN, annual_aid_budget_cents=30_000_000),
            )
            self.assertEqual(post(updated).status_code, 409)
            self.assertContains(post({**updated, "plan_revision": "2"}),
                                'id="projection-remaining-budget">$287,500.00</strong>')
            for role in ("parent", "director_b", "operator"):
                other = Client()
                other.force_login(self.demo[role])
                self.assertEqual(other.post(url, data, secure=True).status_code, 404)
            with self.settings(ROOT_URLCONF="jireh.runtime.urls"):
                self.assertEqual(post(data).status_code, 404)
        self.assertFalse(SyntheticAidOffer.objects.exists())
        self.assertFalse(SyntheticAidSubmission.objects.exists())
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AidApplication.STATUS_DRAFT)
