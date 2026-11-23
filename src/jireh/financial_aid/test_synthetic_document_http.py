"""End-to-end HTTP acceptance for the fixed fictional encrypted-document journey.

No user-supplied file bytes, production routes, real household financial
records, external storage or real antivirus certification are involved.
"""
import json
import uuid

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from jireh.schools.demo_seed import seed_synthetic_browser_demo
from jireh.schools.models import HouseholdAccess

from .models import AidApplication, FinancialDocument, FinancialDocumentEvent
from .services import get_or_create_annual_draft


class FictionalDocumentHTTPTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.demo = seed_synthetic_browser_demo()
        cls.application = get_or_create_annual_draft(
            user=cls.demo["parent"],
            school_id=cls.demo["school_a"].pk,
            household_id=cls.demo["household_a"].pk,
            academic_year_id=cls.demo["year_a"].pk,
        )

    def scoped(self, **overrides):
        values = {
            "school_id": self.demo["school_a"].pk,
            "household_id": self.demo["household_a"].pk,
            "academic_year_id": self.demo["year_a"].pk,
        }
        values.update(overrides)
        return values

    def urls(self, document_id=None, **scope):
        kwargs = self.scoped(**scope)
        root = reverse("jireh_test_fictional_document_list", kwargs=kwargs)
        create = reverse("jireh_test_fictional_document_create", kwargs=kwargs)
        if document_id is None:
            return root, create
        return (
            root, create,
            reverse("jireh_test_fictional_document_read",
                    kwargs={**kwargs, "document_id": document_id}),
            reverse("jireh_test_fictional_document_remove",
                    kwargs={**kwargs, "document_id": document_id}),
        )

    def family(self, *, who="parent", csrf=True):
        client = Client(enforce_csrf_checks=csrf)
        client.force_login(self.demo[who])
        client.get(reverse("jireh_test_family_login"))
        return client

    def create(self, client, key, *, csrf=True, data=None, url=None):
        payload = {"request_key": key} if data is None else data
        kwargs = ({"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}
                  if csrf else {})
        return client.post(
            url or self.urls()[1], data=json.dumps(payload),
            content_type="application/json", **kwargs,
        )

    def remove(self, client, url, *, csrf=True):
        kwargs = ({"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}
                  if csrf else {})
        return client.delete(url, data=b"", content_type="application/octet-stream", **kwargs)

    def test_create_encrypted_readback_list_delete_and_retry(self):
        client = self.family()
        key = str(uuid.uuid4())
        created = self.create(client, key)
        self.assertEqual(created.status_code, 200, created.content)
        value = created.json()
        self.assertEqual(value["status"], "FICTIONAL_DOCUMENT_ACTIVE")
        self.assertTrue(value["demo_only"])
        self.assertEqual(self.create(client, key).json(), value)
        self.assertEqual(FinancialDocument.objects.count(), 1)
        self.assertEqual(FinancialDocumentEvent.objects.count(), 1)

        _root, _create, read, remove = self.urls(uuid.UUID(value["document_id"]))
        listing = client.get(_root)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.json()["documents"]), 1)
        self.assertEqual(listing.json()["documents"][0]["document_id"], value["document_id"])
        self.assertNotIn("object_key", listing.content.decode())
        self.assertNotIn("sha256", listing.content.decode())
        self.assertNotIn("request_key", listing.content.decode())
        self.assertIn("no-store", listing["Cache-Control"])

        pdf = client.get(read)
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF-"))
        self.assertIn(b"FICTIONAL SAMPLE", pdf.content)
        self.assertNotIn(b"personal", pdf.content.lower())
        self.assertEqual(self.remove(client, remove).status_code, 200)
        self.assertEqual(self.remove(client, remove).status_code, 200)
        self.assertEqual(client.get(read).status_code, 404)
        self.assertEqual(client.get(_root).json()["documents"], [])
        self.assertEqual(FinancialDocumentEvent.objects.count(), 2)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, AidApplication.STATUS_DRAFT)

    def test_cross_school_and_unauthorized_family_denied(self):
        client = self.family()
        value = self.create(client, str(uuid.uuid4())).json()
        document_id = uuid.UUID(value["document_id"])
        _root, _create, read, remove = self.urls(document_id)
        outsider = self.family(who="director_a")
        self.assertEqual(outsider.get(read).status_code, 404)
        self.assertEqual(outsider.get(_root).status_code, 404)
        self.assertEqual(self.create(outsider, str(uuid.uuid4())).status_code, 404)

        other = self.scoped(
            school_id=self.demo["school_b"].pk,
            household_id=self.demo["household_b"].pk,
            academic_year_id=self.demo["year_b"].pk,
        )
        for url in self.urls(document_id, **other):
            response = client.get(url) if url.endswith("/read/") or url.endswith("/documents/") else (
                self.remove(client, url) if url.endswith("/remove/") else
                self.create(client, str(uuid.uuid4()), url=url)
            )
            self.assertEqual(response.status_code, 404, response.content)
        self.assertEqual(client.get(read).status_code, 200)
        self.assertEqual(FinancialDocument.objects.count(), 1)
        self.assertEqual(FinancialDocumentEvent.objects.count(), 1)

    def test_revocation_blocks_existing_document_and_new_writes(self):
        client = self.family()
        record = self.create(client, str(uuid.uuid4())).json()
        _root, _create, read, remove = self.urls(uuid.UUID(record["document_id"]))
        HouseholdAccess.objects.filter(
            household=self.demo["household_a"], user=self.demo["parent"]
        ).update(is_active=False)
        self.assertEqual(client.get(read).status_code, 404)
        self.assertEqual(client.get(_root).status_code, 404)
        self.assertEqual(self.create(client, str(uuid.uuid4())).status_code, 404)
        self.assertEqual(self.remove(client, remove).status_code, 404)
        self.assertEqual(FinancialDocumentEvent.objects.count(), 1)

    def test_no_financial_payloads_or_untrusted_document_bytes_accepted(self):
        client = self.family()
        for data in (
            {"request_key": str(uuid.uuid4()), "income_cents": 1234},
            {"request_key": str(uuid.uuid4()), "content": "%PDF-FAKE"},
            {"request_key": "00000000-0000-0000-0000-000000000000"},
            {"request_key": str(uuid.uuid4()).upper()},
            {"request_key": True},
            {},
            [],
        ):
            response = self.create(client, str(uuid.uuid4()), data=data)
            self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(FinancialDocument.objects.exists())

    def test_authentication_csrf_methods_and_switch_are_fail_closed(self):
        unauth = Client()
        root, create = self.urls()
        self.assertEqual(unauth.get(root).status_code, 403)
        self.assertEqual(unauth.get(create).status_code, 405)
        client = self.family()
        self.assertEqual(self.create(client, str(uuid.uuid4()), csrf=False).status_code, 403)
        self.assertEqual(client.get(create).status_code, 405)
        # CSRF middleware rejects the mutation before the GET-only handler.
        self.assertEqual(client.post(root, data=b"{}",
                                     content_type="application/json").status_code, 403)
        with override_settings(JIREH_SYNTHETIC_DOCUMENTS_ONLY=False):
            self.assertEqual(client.get(root).status_code, 403)
            self.assertEqual(self.create(client, str(uuid.uuid4())).status_code, 403)
        with override_settings(ROOT_URLCONF="jireh.runtime.urls"):
            self.assertEqual(client.get(root).status_code, 404)
        self.assertFalse(FinancialDocument.objects.exists())

    def test_query_parameters_and_duplicate_body_fields_are_rejected(self):
        client = self.family()
        root, create = self.urls()
        self.assertEqual(client.get(root + "?guess=1").status_code, 400)
        raw = ('{"request_key":"' + str(uuid.uuid4()) +
               '","request_key":"' + str(uuid.uuid4()) + '"}')
        response = client.post(
            create, data=raw, content_type="application/json",
            HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(FinancialDocument.objects.exists())
