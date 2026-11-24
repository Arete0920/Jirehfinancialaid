"""Disposable HTTPS acceptance for actual selected fictional PDF bytes."""
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from jireh.financial_aid.models import AidApplication, FinancialDocument, FinancialDocumentEvent
from jireh.financial_aid.services import get_or_create_annual_draft
from jireh.financial_aid.synthetic_document_views import (
    _ALLOWED_FIXTURES, _backend, PrivateDocumentStorageError,
)
from .demo_seed import seed_synthetic_browser_demo
from .grant_admin import revoke_household_access
from .models import Household, HouseholdAccess, Student
from .services import link_student_to_household


@override_settings(
    ROOT_URLCONF="jireh.schools.customer_workspace_urls",
    JIREH_CUSTOMER_WORKSPACE_ACCEPTANCE=True,
    JIREH_SYNTHETIC_DOCUMENTS_ONLY=True,
    TEMPLATES=[{
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [], "APP_DIRS": True, "OPTIONS": {},
    }],
)
class WorkspaceDocumentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fixture = seed_synthetic_browser_demo()
        cls.scope = (
            cls.fixture["school_a"].pk, cls.fixture["household_a"].pk,
            cls.fixture["year_a"].pk,
        )
        cls.draft = get_or_create_annual_draft(
            user=cls.fixture["parent"], school_id=cls.scope[0],
            household_id=cls.scope[1], academic_year_id=cls.scope[2],
        )
        cls.separate = Household.objects.create(
            school=cls.fixture["school_a"], name="Fictional separate household",
        )
        cls.separate_parent = get_user_model().objects.create_user(username="fictional-document-other-parent")
        HouseholdAccess.objects.create(household=cls.separate, user=cls.separate_parent)
        child = Student.objects.get(school_id=cls.scope[0], first_name="Jordan")
        link_student_to_household(
            school_id=cls.scope[0], household_id=cls.separate.pk, student_id=child.pk,
        )

    def _url(self, name, *extra, scope=None):
        return reverse("jireh_workspace_" + name, args=(*(scope or self.scope), *extra))

    def _client(self, who="parent", *, user=None):
        client = Client(enforce_csrf_checks=True)
        client.force_login(user or self.fixture[who])
        client.get(reverse("jireh_workspace"), secure=True)
        return client

    def _get(self, client, name, *extra, scope=None):
        return client.get(self._url(name, *extra, scope=scope), secure=True)

    def _headers(self, client, csrf=True):
        headers = {"HTTP_ORIGIN": "https://testserver"}
        if csrf:
            headers["HTTP_X_CSRFTOKEN"] = client.cookies["csrftoken"].value
        return headers

    def _upload(self, client, data, *, key=None, scope=None, csrf=True, media="application/pdf"):
        return client.post(
            self._url("document_upload", scope=scope),
            data=data, content_type=media, secure=True,
            HTTP_X_DOCUMENT_REQUEST_KEY=key or str(uuid4()), **self._headers(client, csrf),
        )

    def _remove(self, client, pk, *, csrf=True):
        return client.delete(
            self._url("document_remove", pk), data=b"", content_type="application/octet-stream",
            secure=True, **self._headers(client, csrf),
        )

    def test_selected_bytes_versions_readback_and_removal(self):
        client = self._client()
        page = self._get(client, "documents")
        self.assertContains(page, "0 listed")
        self.assertIn("no-store", page["Cache-Control"])
        self.assertNotContains(page, "object_key")
        for variant, expected in zip(("original", "corrected"), _ALLOWED_FIXTURES):
            response = self._get(client, "document_sample", variant)
            self.assertEqual(response.content, expected)
        first_key = str(uuid4())
        created = self._upload(client, _ALLOWED_FIXTURES[0], key=first_key)
        self.assertEqual(created.status_code, 200)
        first = created.json()["document_id"]
        self.assertEqual(self._upload(client, _ALLOWED_FIXTURES[0], key=first_key).json(), created.json())
        self.assertEqual(self._upload(client, _ALLOWED_FIXTURES[1], key=first_key).status_code, 409)
        next_response = self._upload(client, _ALLOWED_FIXTURES[1])
        self.assertEqual(next_response.status_code, 200)
        second = next_response.json()["document_id"]
        self.assertEqual(next_response.json()["version"], 2)
        self.assertEqual(self._get(client, "document_read", first).content, _ALLOWED_FIXTURES[0])
        self.assertEqual(self._get(client, "document_read", second).content, _ALLOWED_FIXTURES[1])
        self.assertContains(self._get(client, "documents"), "2 listed")
        self.assertEqual(self._remove(client, first).status_code, 200)
        self.assertEqual(self._remove(client, first).status_code, 200)
        self.assertEqual(self._get(client, "document_read", first).status_code, 404)
        self.assertContains(self._get(client, "documents"), "1 listed")
        self.assertEqual(FinancialDocumentEvent.objects.count(), 3)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AidApplication.STATUS_DRAFT)

    def test_reject_unsafe_bytes_and_csrf_without_persisting(self):
        client = self._client()
        for data, media in (
            (b"%PDF-1.7 arbitrary %%EOF", "application/pdf"),
            (_ALLOWED_FIXTURES[0] + b"x", "application/pdf"),
            (b"x" * 4097, "application/pdf"),
            (b"", "application/pdf"),
            (_ALLOWED_FIXTURES[0], "text/plain"),
        ):
            self.assertEqual(self._upload(client, data, media=media).status_code, 400)
        self.assertEqual(self._upload(client, _ALLOWED_FIXTURES[0], key="invalid").status_code, 400)
        self.assertEqual(self._upload(client, _ALLOWED_FIXTURES[0], csrf=False).status_code, 403)
        self.assertFalse(FinancialDocument.objects.exists())

    def test_scope_revocation_and_closed_runtime(self):
        client = self._client()
        saved = self._upload(client, _ALLOWED_FIXTURES[0])
        self.assertEqual(saved.status_code, 200)
        pk = saved.json()["document_id"]
        for outsider in (self._client("director_a"), self._client("director_b"),
                         self._client("operator"), self._client(user=self.separate_parent)):
            self.assertEqual(self._get(outsider, "documents").status_code, 404)
            self.assertEqual(self._get(outsider, "document_read", pk).status_code, 404)
            self.assertEqual(self._upload(outsider, _ALLOWED_FIXTURES[0]).status_code, 404)
            self.assertEqual(self._remove(outsider, pk).status_code, 404)
        for wrong in (
            (self.scope[0], self.separate.pk, self.scope[2]),
            (self.scope[0], self.scope[1], self.fixture["year_b"].pk),
            (self.fixture["school_b"].pk, self.fixture["household_b"].pk, self.fixture["year_b"].pk),
        ):
            self.assertEqual(self._get(client, "document_read", pk, scope=wrong).status_code, 404)
            self.assertEqual(self._upload(client, _ALLOWED_FIXTURES[0], scope=wrong).status_code, 404)
        revoke_household_access(
            actor=self.fixture["director_a"], school_id=self.scope[0],
            household_id=self.scope[1], subject_user_id=self.fixture["parent"].pk,
        )
        self.assertEqual(self._get(client, "documents").status_code, 404)
        self.assertEqual(self._get(client, "document_read", pk).status_code, 404)
        self.assertEqual(self._remove(client, pk).status_code, 404)
        self.assertEqual(FinancialDocumentEvent.objects.count(), 1)
        url = self._url("documents")
        with override_settings(ROOT_URLCONF="jireh.runtime.urls"):
            self.assertEqual(client.get(url, secure=True).status_code, 404)

    def test_removal_failure_is_unreadable_and_recoverable(self):
        client = self._client()
        saved = self._upload(client, _ALLOWED_FIXTURES[0])
        self.assertEqual(saved.status_code, 200)
        pk = saved.json()["document_id"]
        with patch.object(_backend(), "delete", side_effect=PrivateDocumentStorageError("fictional_failure")):
            self.assertEqual(self._remove(client, pk).status_code, 409)
        self.assertEqual(self._get(client, "document_read", pk).status_code, 404)
        self.assertContains(self._get(client, "documents"), "Removal pending")
        self.assertEqual(FinancialDocumentEvent.objects.count(), 1)
        self.assertEqual(self._remove(client, pk).status_code, 200)
        self.assertContains(self._get(client, "documents"), "0 listed")
        self.assertEqual(FinancialDocumentEvent.objects.count(), 2)

    def test_disabled_gate_and_storage_failure(self):
        client = self._client()
        with override_settings(JIREH_SYNTHETIC_DOCUMENTS_ONLY=False):
            self.assertEqual(self._get(client, "documents").status_code, 403)
            self.assertEqual(self._upload(client, _ALLOWED_FIXTURES[0]).status_code, 403)
        with patch("jireh.schools.workspace_documents._backend", side_effect=PrivateDocumentStorageError("fixture_unavailable")):
            self.assertEqual(self._upload(client, _ALLOWED_FIXTURES[0]).status_code, 503)
        self.assertFalse(FinancialDocument.objects.exists())
