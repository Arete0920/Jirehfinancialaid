"""HTTPS-mode HTTP acceptance for the generic workspace; never a live service."""
import json
import secrets
from urllib.parse import urlencode
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from jireh.financial_aid.models import (
    AidApplication, AidApplicationStudent, SyntheticQuestionnaireDraft,
    SyntheticQuestionnaireEvent,
)
from jireh.schools.demo_seed import DEMO_PASSWORD, seed_synthetic_browser_demo
from jireh.schools.grant_admin import revoke_household_access
from jireh.schools.models import Household, HouseholdAccess, Student
from jireh.schools.services import link_student_to_household


@override_settings(
    ROOT_URLCONF="jireh.schools.customer_workspace_urls",
    JIREH_CUSTOMER_WORKSPACE_ACCEPTANCE=True,
    JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE=True,
    JIREH_SYNTHETIC_QUESTIONNAIRE_KEY=secrets.token_bytes(32),
    TEMPLATES=[{
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [], "APP_DIRS": True, "OPTIONS": {},
    }],
)
class CustomerWorkspaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fixture = seed_synthetic_browser_demo()
        cls.separate = Household.objects.create(
            school=cls.fixture["school_a"], name="Separate household",
        )
        cls.other_parent = get_user_model().objects.create_user(username="other-parent")
        HouseholdAccess.objects.create(household=cls.separate, user=cls.other_parent)
        cls.child = Student.objects.get(
            school=cls.fixture["school_a"], first_name="Jordan",
        )
        link_student_to_household(
            school_id=cls.child.school_id, household_id=cls.separate.pk,
            student_id=cls.child.pk,
        )
        cls.scope = (
            cls.fixture["school_a"].pk, cls.fixture["household_a"].pk,
            cls.fixture["year_a"].pk,
        )

    def _client(self, key):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.fixture[key])
        return client

    def _get(self, client, name, *args):
        return client.get(reverse(name, args=args), secure=True)

    def _post(self, client, name, *args, csrf=True):
        headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value} if csrf else {}
        return client.post(reverse(name, args=args), secure=True,
                           HTTP_REFERER="https://testserver/workspace/", **headers)

    def test_generic_login_logout_and_private_headers(self):
        client = Client(enforce_csrf_checks=True)
        page = self._get(client, "jireh_workspace")
        self.assertContains(page, "Sign in")
        self.assertNotContains(page, DEMO_PASSWORD)
        self.assertIn("no-store", page["Cache-Control"])
        self.assertEqual(page["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'none'", page["Content-Security-Policy"])
        login = reverse("jireh_workspace_login")
        response = client.post(
            login, data=json.dumps({
                "username": self.fixture["parent"].username,
                "password": DEMO_PASSWORD,
            }), content_type="application/json", secure=True,
            HTTP_REFERER="https://testserver/workspace/",
            HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(self._get(client, "jireh_workspace"), "Sample Family")
        self.assertEqual(self._post(client, "jireh_workspace_logout").status_code, 200)
        self.assertEqual(self._get(client, "jireh_workspace_family", *self.scope).status_code, 403)

    def test_family_draft_and_director_readback(self):
        family = self._client("parent")
        page = self._get(family, "jireh_workspace_family", *self.scope)
        self.assertContains(page, "No draft exists")
        self.assertEqual(AidApplication.objects.count(), 0)
        self.assertEqual(self._post(family, "jireh_workspace_draft", *self.scope,
                                    csrf=False).status_code, 403)
        draft = self._post(family, "jireh_workspace_draft", *self.scope)
        self.assertEqual(draft.status_code, 200)
        self.assertEqual(self._post(family, "jireh_workspace_draft", *self.scope).json(),
                         draft.json())
        self.assertEqual(AidApplication.objects.count(), 1)
        for child in Student.objects.filter(school_id=self.scope[0]):
            self.assertEqual(self._post(
                family, "jireh_workspace_select", *self.scope, child.pk,
            ).status_code, 200)
        self.assertContains(self._get(family, "jireh_workspace_family", *self.scope),
                            "2 selected")
        self.assertEqual(AidApplicationStudent.objects.count(), 2)
        director = self._client("director_a")
        page = self._get(director, "jireh_workspace_director", self.scope[0], self.scope[2])
        self.assertContains(page, draft.json()["id"])
        self.assertContains(page, 'id="child-total">2</strong>')
        case = self._get(director, "jireh_workspace_case",
                         self.scope[0], self.scope[2], draft.json()["id"])
        self.assertContains(case, 'id="case-child-count">2</strong>')

    def test_home_lists_explicit_grants_only(self):
        family = self._client("parent")
        page = self._get(family, "jireh_workspace")
        self.assertContains(page, "Sample Family")
        self.assertNotContains(page, "Separate household")
        self.assertNotContains(page, "Synthetic School B")
        self.assertNotContains(page, "School director</h2>")
        director = self._client("director_b")
        page = self._get(director, "jireh_workspace")
        self.assertContains(page, "Synthetic School B")
        self.assertNotContains(page, "Synthetic Christian Academy")
        self.assertNotContains(page, "Sample Family")

    def test_cross_school_same_child_and_role_denials(self):
        family = self._client("parent")
        self._get(family, "jireh_workspace")
        separate = (self.scope[0], self.separate.pk, self.scope[2])
        for scope in (
            separate,
            (self.fixture["school_b"].pk, self.fixture["household_b"].pk,
             self.fixture["year_b"].pk),
            (self.scope[0], self.scope[1], self.fixture["year_b"].pk),
        ):
            result = self._get(family, "jireh_workspace_family", *scope)
            self.assertEqual(result.status_code, 404)
            self.assertIn("no-store", result["Cache-Control"])
            self.assertEqual(self._post(family, "jireh_workspace_draft", *scope).status_code, 404)
        self.assertEqual(AidApplication.objects.count(), 0)
        self.assertEqual(self._get(family, "jireh_workspace_director",
                                   self.scope[0], self.scope[2]).status_code, 404)
        for role in ("director_a", "operator"):
            self.assertEqual(self._get(self._client(role), "jireh_workspace_family",
                                       *self.scope).status_code, 404)
        self.assertEqual(self._get(self._client("director_b"), "jireh_workspace_director",
                                   self.scope[0], self.scope[2]).status_code, 404)

    def test_revocation_denies_existing_session_and_mutation(self):
        family = self._client("parent")
        self._get(family, "jireh_workspace")
        revoke_household_access(
            actor=self.fixture["director_a"], school_id=self.scope[0],
            household_id=self.scope[1], subject_user_id=self.fixture["parent"].pk,
        )
        self.assertNotContains(self._get(family, "jireh_workspace"), "Sample Family")
        self.assertEqual(self._get(family, "jireh_workspace_family", *self.scope).status_code, 404)
        self.assertEqual(self._post(family, "jireh_workspace_draft", *self.scope).status_code, 404)
        self.assertEqual(AidApplication.objects.count(), 0)

    def test_guard_requires_https_and_explicit_disposable_opt_in(self):
        self.assertEqual(self.client.get("/workspace/").status_code, 404)
        with override_settings(JIREH_CUSTOMER_WORKSPACE_ACCEPTANCE=False):
            self.assertEqual(self.client.get("/workspace/", secure=True).status_code, 404)
        with patch.dict("os.environ", {"DJANGO_SETTINGS_MODULE": "jireh.runtime.settings"}):
            self.assertEqual(self.client.get("/workspace/", secure=True).status_code, 404)
        with override_settings(ROOT_URLCONF="jireh.runtime.urls"):
            self.assertEqual(self.client.get("/workspace/", secure=True).status_code, 404)
            self.assertEqual(self.client.get("/workspace/sign-in/", secure=True).status_code, 404)

    def test_no_fixture_or_financial_mutation_routes_in_allowlist(self):
        for path in ("/local-demo/", "/test-auth/login/", "/api/v1/",
                     "/workspace/submit/", "/workspace/pay/", "/workspace/awards/"):
            self.assertEqual(self.client.get(path, secure=True).status_code, 404)

    def _questionnaire_payload(self, revision=0, amount="1234.56", initial=0):
        data = {"revision": str(revision)}
        for section in ("income", "assets", "liabilities", "expenses"):
            data[f"{section}-TOTAL_FORMS"] = "1"
            data[f"{section}-INITIAL_FORMS"] = str(initial if section == "income" else 0)
        data.update({
            "income-0-category": "EMPLOYMENT", "income-0-value": amount,
            "income-0-period_start": "2026-01-01", "income-0-period_end": "2026-12-31",
        })
        return data

    def _questionnaire_post(self, client, data, scope=None, csrf=True):
        headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value} if csrf else {}
        return client.post(
            reverse("jireh_workspace_questionnaire", args=scope or self.scope),
            data=urlencode(data), content_type="application/x-www-form-urlencoded",
            secure=True, HTTP_REFERER="https://testserver/workspace/", **headers,
        )

    def _start_questionnaire(self):
        family = self._client("parent")
        self._get(family, "jireh_workspace_family", *self.scope)
        self.assertEqual(self._post(family, "jireh_workspace_draft", *self.scope).status_code, 200)
        page = self._get(family, "jireh_workspace_questionnaire", *self.scope)
        self.assertContains(page, "Saved revision: 0")
        self.assertIn("no-store", page["Cache-Control"])
        return family

    def test_questionnaire_http_save_resume_correct_delete(self):
        from django.conf import settings
        from jireh.financial_aid.synthetic_questionnaire_storage import read_fictional_questionnaire

        family = self._start_questionnaire()
        initial = self._questionnaire_payload()
        self.assertEqual(self._questionnaire_post(family, initial).status_code, 302)
        self.assertContains(self._get(family, "jireh_workspace_questionnaire", *self.scope),
                            'value="1234.56"')
        self.assertEqual(self._questionnaire_post(family, initial).status_code, 409)
        scope = dict(user=self.fixture["parent"], school_id=self.scope[0],
                     household_id=self.scope[1], academic_year_id=self.scope[2],
                     key=settings.JIREH_SYNTHETIC_QUESTIONNAIRE_KEY)
        revision, saved = read_fictional_questionnaire(**scope)
        self.assertEqual((revision, saved["income"][0]["amount"]), (1, 123456))
        corrected = self._questionnaire_payload(1, "765.43", initial=1)
        self.assertEqual(self._questionnaire_post(family, corrected).status_code, 302)
        self.assertContains(self._get(family, "jireh_workspace_questionnaire", *self.scope),
                            'value="765.43"')
        removed = self._questionnaire_payload(2, "765.43", initial=1)
        removed["income-0-DELETE"] = "on"
        self.assertEqual(self._questionnaire_post(family, removed).status_code, 302)
        self.assertEqual(read_fictional_questionnaire(**scope), (3, {}))
        self.assertEqual(SyntheticQuestionnaireEvent.objects.count(), 3)
        self.assertEqual(AidApplication.objects.get().status, AidApplication.STATUS_DRAFT)

    def test_questionnaire_invalid_csrf_scope_and_revocation_are_nonmutating(self):
        family = self._start_questionnaire()
        data = self._questionnaire_payload()
        self.assertEqual(self._questionnaire_post(family, data, csrf=False).status_code, 403)
        invalid = self._questionnaire_payload(amount="1.001")
        self.assertEqual(self._questionnaire_post(family, invalid).status_code, 400)
        invalid = self._questionnaire_payload()
        invalid["income-0-period_start"] = "2025-01-01"
        self.assertEqual(self._questionnaire_post(family, invalid).status_code, 400)
        self.assertEqual(SyntheticQuestionnaireDraft.objects.count(), 0)
        self.assertEqual(self._questionnaire_post(family, data).status_code, 302)
        for scope in (
            (self.scope[0], self.separate.pk, self.scope[2]),
            (self.fixture["school_b"].pk, self.fixture["household_b"].pk,
             self.fixture["year_b"].pk),
            (self.scope[0], self.scope[1], self.fixture["year_b"].pk),
        ):
            self.assertEqual(self._get(family, "jireh_workspace_questionnaire", *scope).status_code, 404)
            self.assertEqual(self._questionnaire_post(family, data, scope=scope).status_code, 404)
        for role in ("director_a", "director_b", "operator"):
            client = self._client(role)
            self._get(client, "jireh_workspace")
            self.assertEqual(self._get(client, "jireh_workspace_questionnaire", *self.scope).status_code, 404)
            self.assertEqual(self._questionnaire_post(client, data).status_code, 404)
        with override_settings(JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE=False):
            self.assertEqual(self._get(family, "jireh_workspace_questionnaire", *self.scope).status_code, 403)
        revoke_household_access(
            actor=self.fixture["director_a"], school_id=self.scope[0],
            household_id=self.scope[1], subject_user_id=self.fixture["parent"].pk,
        )
        self.assertEqual(self._get(family, "jireh_workspace_questionnaire", *self.scope).status_code, 404)
        self.assertEqual(self._questionnaire_post(family, data).status_code, 404)
        self.assertEqual(SyntheticQuestionnaireDraft.objects.get().revision, 1)
        self.assertEqual(SyntheticQuestionnaireEvent.objects.count(), 1)
