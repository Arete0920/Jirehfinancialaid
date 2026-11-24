"""Disposable application review HTTP and database acceptance."""
import json
import secrets
from pathlib import Path
from unittest import skipUnless
from urllib.parse import urlencode
from uuid import uuid4

from django.db import IntegrityError, connection, transaction
from django.test import Client, TestCase, override_settings
from django.test.client import MULTIPART_CONTENT
from django.urls import reverse

from jireh.financial_aid.document_lifecycle import create_synthetic_document, delete_synthetic_document
from jireh.financial_aid.models import (
    AidApplication, SyntheticAidSubmission, SyntheticApplicationReview,
)
from jireh.financial_aid.services import get_or_create_annual_draft, select_student_for_draft
from jireh.financial_aid.synthetic_application_review import read_fictional_application_review
from jireh.financial_aid.synthetic_document_views import _ALLOWED_FIXTURES, _POLICY, _backend
from jireh.financial_aid.synthetic_questionnaire_storage import (
    FictionalQuestionnairePolicy, save_fictional_questionnaire,
)
from .demo_seed import seed_synthetic_browser_demo
from .grant_admin import revoke_household_access
from .models import Student


@override_settings(
    ROOT_URLCONF="jireh.schools.customer_workspace_urls",
    JIREH_CUSTOMER_WORKSPACE_ACCEPTANCE=True,
    JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE=True,
    JIREH_SYNTHETIC_DOCUMENTS_ONLY=True,
    JIREH_SYNTHETIC_APPLICATION_REVIEW=True,
    JIREH_SYNTHETIC_QUESTIONNAIRE_KEY=secrets.token_bytes(32),
    TEMPLATES=[{
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [], "APP_DIRS": True, "OPTIONS": {},
    }],
)
class WorkspaceReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fixture = seed_synthetic_browser_demo()
        cls.ids = dict(
            school_id=cls.fixture["school_a"].pk,
            household_id=cls.fixture["household_a"].pk,
            academic_year_id=cls.fixture["year_a"].pk,
        )
        cls.scope = dict(user=cls.fixture["parent"], **cls.ids)
        cls.draft = get_or_create_annual_draft(**cls.scope)
        cls.children = list(Student.objects.filter(school_id=cls.ids["school_id"]).order_by("first_name"))

    def setUp(self):
        from django.conf import settings
        self.key = settings.JIREH_SYNTHETIC_QUESTIONNAIRE_KEY
        self.member = str(uuid4())
        self.catalog = json.loads(
            (Path(__file__).resolve().parents[3] / "docs" / "questionnaire_v1_field_catalog.json")
            .read_text(encoding="utf-8")
        )
        self.policy = FictionalQuestionnairePolicy(
            reporting_year=2026, min_cents=0, max_cents=100000000,
            categories=(("EMPLOYMENT",), ("CASH",), ("MORTGAGE",), ("HOUSING",)),
            member_ids=(self.member,),
        )
        self.answers = {
            "income": [{"category": "EMPLOYMENT", "amount": 76543,
                        "period_start": "2026-01-01", "period_end": "2026-12-31",
                        "contributor_id": self.member}],
            "assets": [{"category": "CASH", "balance": 0, "as_of_date": "2026-06-30",
                        "owner_member_id": self.member}],
            "liabilities": [{"category": "MORTGAGE", "balance": 123456,
                             "as_of_date": "2026-06-30", "responsible_member_id": self.member}],
            "expenses": [{"category": "HOUSING", "amount": 98765,
                          "period_start": "2026-01-01", "period_end": "2026-01-31"}],
        }
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.fixture["parent"])
        self.url = reverse("jireh_workspace_review", kwargs=self.ids)
        self.client.get(self.url, secure=True)

    def save(self, revision=0):
        return save_fictional_questionnaire(
            **self.scope, expected_revision=revision, answers=self.answers,
            catalog=self.catalog, policy=self.policy, key=self.key,
        )

    def upload(self):
        return create_synthetic_document(
            **self.scope, request_key=str(uuid4()), category="FICTIONAL_TAX",
            data=_ALLOWED_FIXTURES[0], policy=_POLICY, backend=_backend(),
        )

    def prepare(self):
        select_student_for_draft(**self.scope, student_id=self.children[0].pk)
        self.save()
        return self.upload()

    def state(self):
        return read_fictional_application_review(**self.scope, key=self.key)

    def confirm(self, digest, *, reviewed="yes", csrf=True):
        headers = {"HTTP_ORIGIN": "https://testserver"}
        if csrf:
            headers["HTTP_X_CSRFTOKEN"] = self.client.cookies["csrftoken"].value
        return self.client.post(
            self.url, urlencode({"state_digest": digest, "reviewed": reviewed}),
            content_type="application/x-www-form-urlencoded",
            secure=True, **headers,
        )

    def test_confirmation_rejects_multipart(self):
        self.prepare()
        response = self.client.post(
            self.url, {"state_digest": self.state()["digest"], "reviewed": "yes"},
            content_type=MULTIPART_CONTENT, secure=True,
            HTTP_ORIGIN="https://testserver",
            HTTP_X_CSRFTOKEN=self.client.cookies["csrftoken"].value,
        )
        self.assertContains(response, "Explicit fictional review required.", status_code=400)
        self.assertFalse(SyntheticApplicationReview.objects.exists())

    def test_incomplete_explicit_confirmation_and_stale_digest(self):
        self.assertContains(self.client.get(self.url, secure=True), "Incomplete rehearsal")
        self.assertEqual(self.confirm(self.state()["digest"]).status_code, 400)
        self.prepare()
        digest = self.state()["digest"]
        self.assertContains(self.client.get(self.url, secure=True), "$55.00")
        self.assertEqual(self.confirm(digest, reviewed="no").status_code, 400)
        self.assertEqual(self.confirm(digest, csrf=False).status_code, 403)
        self.assertEqual(self.confirm("invalid").status_code, 409)
        self.assertEqual(self.confirm("é" * 64).status_code, 409)
        self.assertEqual(self.confirm(digest).status_code, 302)
        self.assertEqual(self.confirm(digest).status_code, 302)
        self.assertEqual(SyntheticApplicationReview.objects.count(), 1)
        self.assertContains(self.client.get(self.url, secure=True), "Current fictional review confirmed")
        self.answers["income"][0]["amount"] = 76544
        self.save(1)
        self.assertEqual(self.confirm(digest).status_code, 409)
        self.assertContains(self.client.get(self.url, secure=True), "Review required")
        self.assertEqual(self.confirm(self.state()["digest"]).status_code, 302)
        self.assertEqual(SyntheticApplicationReview.objects.count(), 2)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AidApplication.STATUS_DRAFT)
        self.assertFalse(SyntheticAidSubmission.objects.exists())

    def test_selection_and_document_changes_invalidate_confirmation(self):
        original = self.prepare()
        digest = self.state()["digest"]
        self.assertEqual(self.confirm(digest).status_code, 302)
        select_student_for_draft(**self.scope, student_id=self.children[1].pk)
        self.assertEqual(self.confirm(digest).status_code, 409)
        next_digest = self.state()["digest"]
        self.assertEqual(self.confirm(next_digest).status_code, 302)
        self.upload()
        self.assertEqual(self.confirm(next_digest).status_code, 409)
        current = self.state()["digest"]
        delete_synthetic_document(**self.scope, document_id=original.pk, backend=_backend())
        self.assertEqual(self.confirm(current).status_code, 409)
        self.assertIsNone(self.state()["confirmation"])

    def test_scope_revocation_and_closed_runtime(self):
        self.prepare()
        digest = self.state()["digest"]
        for who in ("director_a", "director_b", "operator"):
            other = Client()
            other.force_login(self.fixture[who])
            self.assertEqual(other.get(self.url, secure=True).status_code, 404)
        with override_settings(JIREH_SYNTHETIC_APPLICATION_REVIEW=False):
            self.assertEqual(self.client.get(self.url, secure=True).status_code, 403)
        with override_settings(ROOT_URLCONF="jireh.runtime.urls"):
            self.assertEqual(self.client.get(self.url, secure=True).status_code, 404)
        revoke_household_access(
            actor=self.fixture["director_a"], school_id=self.ids["school_id"],
            household_id=self.ids["household_id"], subject_user_id=self.fixture["parent"].pk,
        )
        self.assertEqual(self.client.get(self.url, secure=True).status_code, 404)
        self.assertEqual(self.confirm(digest).status_code, 404)
        self.assertFalse(SyntheticApplicationReview.objects.exists())

    @skipUnless(connection.vendor == "postgresql", "PostgreSQL trigger acceptance")
    def test_postgresql_review_evidence_cannot_be_rewritten(self):
        self.prepare()
        self.assertEqual(self.confirm(self.state()["digest"]).status_code, 302)
        row = SyntheticApplicationReview.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            SyntheticApplicationReview.objects.filter(pk=row.pk).update(state_digest="0" * 64)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SyntheticApplicationReview.objects.filter(pk=row.pk).delete()
        self.assertEqual(SyntheticApplicationReview.objects.count(), 1)
