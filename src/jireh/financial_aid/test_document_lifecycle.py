"""Disposable scoped document lifecycle acceptance: never use customer bytes."""
import os
import tempfile
import uuid
from pathlib import Path
from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection, transaction
from django.http import Http404
from django.test import TestCase, TransactionTestCase, override_settings

from jireh.schools.models import AcademicYear, Household, HouseholdAccess, School
from .models import AidApplication, FinancialDocument, FinancialDocumentEvent
from .services import get_or_create_annual_draft
from .document_lifecycle import (
    DocumentLifecycleError, SyntheticDocumentPolicy,
    create_synthetic_document, read_synthetic_document, delete_synthetic_document,
)


class DisposableStore:
    synthetic_only = True
    private_storage = True
    encrypted_storage = True  # test double capability assertion only, not cryptography

    def __init__(self):
        self.objects = {}
        self.scan_ok = True
        self.fail_put = False
        self.fail_delete = False

    def inspect(self, data):
        return ("application/pdf" if data.startswith(b"%PDF-") else "text/plain", self.scan_ok)

    def put(self, key, data):
        if self.fail_put:
            raise RuntimeError("synthetic backend unavailable")
        self.objects[key] = data

    def get(self, key):
        return self.objects[key]

    def delete(self, key):
        if self.fail_delete:
            raise RuntimeError("synthetic deletion unavailable")
        self.objects.pop(key, None)


class DocumentLifecycleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username="fictional-doc-parent")
        cls.foreign = User.objects.create_user(username="fictional-doc-foreign")
        cls.superuser = User.objects.create_superuser(
            username="fictional-doc-admin", email="doc-admin@example.invalid",
            password="test-only-password",
        )
        cls.school = School.objects.create(code="fictional-doc-a", name="Fictional A")
        cls.other_school = School.objects.create(code="fictional-doc-b", name="Fictional B")
        cls.year = AcademicYear.objects.create(
            school=cls.school, name="2026-27",
            start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
        )
        cls.other_year = AcademicYear.objects.create(
            school=cls.other_school, name="2026-27",
            start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
        )
        cls.house = Household.objects.create(school=cls.school, name="Fictional A family")
        cls.other_house = Household.objects.create(
            school=cls.other_school, name="Fictional B family"
        )
        HouseholdAccess.objects.create(user=cls.user, household=cls.house)
        HouseholdAccess.objects.create(user=cls.foreign, household=cls.other_house)

    def setUp(self):
        self.store = DisposableStore()
        self.contents = b"%PDF-1.7\nFICTIONAL RECORD\n%%EOF"
        self.request_key = str(uuid.uuid4())
        self.policy = SyntheticDocumentPolicy(
            version="fictional-policy-v1",
            allowed_categories=("FICTIONAL_TAX",),
            allowed_media_types=("application/pdf",),
            maximum_bytes=4096,
        )
        self.application = get_or_create_annual_draft(
            user=self.user, school_id=self.school.pk,
            household_id=self.house.pk, academic_year_id=self.year.pk,
        )

    def params(self, **changes):
        original = dict(
            user=self.user, school_id=self.school.pk,
            household_id=self.house.pk, academic_year_id=self.year.pk,
            request_key=self.request_key, category="FICTIONAL_TAX",
            data=self.contents, policy=self.policy, backend=self.store,
        )
        original.update(changes)
        return original

    def scope(self, **changes):
        scope = dict(
            user=self.user, school_id=self.school.pk,
            household_id=self.house.pk, academic_year_id=self.year.pk,
            backend=self.store,
        )
        scope.update(changes)
        return scope

    def test_store_read_retry_and_versioned_metadata(self):
        first = create_synthetic_document(**self.params())
        same = create_synthetic_document(**self.params())
        self.assertEqual(first.pk, same.pk)
        self.assertEqual(first.version, 1)
        self.assertEqual(first.school_id, self.school.pk)
        self.assertEqual(first.household_id, self.house.pk)
        self.assertEqual(first.application_id, self.application.pk)
        self.assertEqual(len(self.store.objects), 1)
        self.assertEqual(
            read_synthetic_document(**self.scope(), document_id=first.pk),
            self.contents,
        )
        second = create_synthetic_document(
            **self.params(request_key=str(uuid.uuid4()))
        )
        self.assertEqual(second.version, 2)
        self.assertEqual(FinancialDocument.objects.count(), 2)
        self.assertEqual(
            list(FinancialDocumentEvent.objects.order_by("created_at").values_list("action", flat=True)),
            ["CREATED", "CREATED"],
        )
        self.assertNotIn("FICTIONAL RECORD", repr(first))

    def test_strict_scoping_revocation_and_admin_denial(self):
        doc = create_synthetic_document(**self.params())
        for who, school, household, year in (
            (self.foreign, self.school, self.house, self.year),
            (self.superuser, self.school, self.house, self.year),
            (self.user, self.other_school, self.house, self.year),
            (self.user, self.school, self.other_house, self.year),
            (self.user, self.school, self.house, self.other_year),
        ):
            with self.subTest(who=who.username, school=school.code):
                with self.assertRaises((PermissionDenied, Http404)):
                    read_synthetic_document(
                        **self.scope(
                            user=who, school_id=school.pk, household_id=household.pk,
                            academic_year_id=year.pk,
                        ),
                        document_id=doc.pk,
                    )
        HouseholdAccess.objects.filter(
            user=self.user, household=self.house
        ).update(is_active=False)
        with self.assertRaises(Http404):
            read_synthetic_document(**self.scope(), document_id=doc.pk)
        with self.assertRaises(Http404):
            create_synthetic_document(**self.params())

    def test_wrong_household_and_application_do_not_leak(self):
        doc = create_synthetic_document(**self.params())
        with self.assertRaises(Http404):
            delete_synthetic_document(
                **self.scope(user=self.foreign), document_id=doc.pk
            )
        self.assertEqual(doc.state, FinancialDocument.STATE_ACTIVE)
        self.assertEqual(len(self.store.objects), 1)

    def test_delete_is_tombstoned_then_audited_and_idempotent(self):
        doc = create_synthetic_document(**self.params())
        removed = delete_synthetic_document(**self.scope(), document_id=doc.pk)
        self.assertEqual(removed.state, FinancialDocument.STATE_DELETED)
        self.assertFalse(self.store.objects)
        self.assertIsNotNone(removed.deleted_at)
        with self.assertRaises(Http404):
            read_synthetic_document(**self.scope(), document_id=doc.pk)
        retry = delete_synthetic_document(**self.scope(), document_id=doc.pk)
        self.assertEqual(retry.pk, doc.pk)
        self.assertEqual(
            list(FinancialDocumentEvent.objects.order_by("created_at").values_list("action", flat=True)),
            ["CREATED", "DELETED"],
        )
        with self.assertRaises(DocumentLifecycleError):
            create_synthetic_document(**self.params())

    def test_failed_delete_never_leaks_contents_to_reader(self):
        doc = create_synthetic_document(**self.params())
        self.store.fail_delete = True
        with self.assertRaisesRegex(DocumentLifecycleError, "document_storage_delete_failed"):
            delete_synthetic_document(**self.scope(), document_id=doc.pk)
        doc.refresh_from_db()
        self.assertEqual(doc.state, FinancialDocument.STATE_DELETE_PENDING)
        self.assertEqual(len(self.store.objects), 1)
        with self.assertRaises(Http404):
            read_synthetic_document(**self.scope(), document_id=doc.pk)
        self.store.fail_delete = False
        done = delete_synthetic_document(**self.scope(), document_id=doc.pk)
        self.assertEqual(done.state, FinancialDocument.STATE_DELETED)
        self.assertFalse(self.store.objects)

    def test_scan_content_and_backend_gate_are_enforced(self):
        self.store.scan_ok = False
        with self.assertRaisesRegex(DocumentLifecycleError, "document_scan_rejected"):
            create_synthetic_document(**self.params())
        self.store.scan_ok = True
        with self.assertRaisesRegex(DocumentLifecycleError, "document_detected_type_denied"):
            create_synthetic_document(**self.params(data=b"<script>not-pdf</script>"))
        self.assertFalse(self.store.objects)
        self.store.encrypted_storage = False
        with self.assertRaisesRegex(DocumentLifecycleError, "synthetic_backend_required"):
            create_synthetic_document(**self.params())
        self.assertEqual(FinancialDocument.objects.count(), 0)

    def test_unsupported_policy_size_idempotency_and_corruption(self):
        with self.assertRaisesRegex(DocumentLifecycleError, "document_size_denied"):
            create_synthetic_document(**self.params(data=b"%PDF-" + b"x" * 5000))
        with self.assertRaisesRegex(DocumentLifecycleError, "document_request_key_invalid"):
            create_synthetic_document(**self.params(request_key="noncanonical"))
        doc = create_synthetic_document(**self.params())
        with self.assertRaisesRegex(DocumentLifecycleError, "document_request_conflict"):
            create_synthetic_document(**self.params(data=self.contents + b"x"))
        self.store.objects[str(doc.object_key)] = b"%PDF-tampered"
        with self.assertRaisesRegex(DocumentLifecycleError, "document_integrity_failed"):
            read_synthetic_document(**self.scope(), document_id=doc.pk)

    def test_storage_failure_produces_no_metadata_or_event(self):
        self.store.fail_put = True
        with self.assertRaises(RuntimeError):
            create_synthetic_document(**self.params())
        self.assertFalse(FinancialDocument.objects.exists())
        self.assertFalse(FinancialDocumentEvent.objects.exists())
        self.assertFalse(self.store.objects)

    def test_flag_disabled_even_for_disposable_store(self):
        with override_settings(JIREH_SYNTHETIC_DOCUMENTS_ONLY=False):
            with self.assertRaises(PermissionDenied):
                create_synthetic_document(**self.params())

    def test_immutable_identity_and_audit_binding_on_model_paths(self):
        doc = create_synthetic_document(**self.params())
        doc.category = "OTHER"
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            doc.save()
        event = FinancialDocumentEvent.objects.get(document=doc)
        with self.assertRaises(ValidationError):
            event.delete()
        with self.assertRaises(ValidationError):
            doc.delete()


    def test_encrypted_preproduction_backend_roundtrip_through_scoped_service(self):
        from .local_encrypted_backend import LocalEncryptedClamdBackend

        class VerifiedFakeScanner:
            def scan(self, content):
                return content.startswith(b"%PDF-") and b"%%EOF" in content[-1024:]

        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory, 0o700)
            storage = LocalEncryptedClamdBackend(
                root=Path(directory),
                encryption_key=os.urandom(32),
                scanner=VerifiedFakeScanner(),
                max_bytes=4096,
            )
            doc = create_synthetic_document(**self.params(backend=storage))
            files = list(Path(directory).iterdir())
            self.assertEqual(len(files), 1)
            self.assertNotIn(b"FICTIONAL RECORD", files[0].read_bytes())
            self.assertEqual(
                read_synthetic_document(
                    **self.scope(backend=storage), document_id=doc.pk
                ),
                self.contents,
            )
            with self.assertRaises(Http404):
                read_synthetic_document(
                    **self.scope(backend=storage, user=self.foreign),
                    document_id=doc.pk,
                )
            removed = delete_synthetic_document(
                **self.scope(backend=storage), document_id=doc.pk,
            )
            self.assertEqual(removed.state, FinancialDocument.STATE_DELETED)
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertEqual(
                list(FinancialDocumentEvent.objects.filter(document=doc)
                     .order_by("created_at").values_list("action", flat=True)),
                ["CREATED", "DELETED"],
            )


class DocumentPostgresGuardTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL evidence only")
        User = get_user_model()
        self.parent = User.objects.create_user(username="pg-document-owner")
        self.school = School.objects.create(code="pg-document-a", name="PG A")
        self.year = AcademicYear.objects.create(
            school=self.school, name="2026-27",
            start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
        )
        self.house = Household.objects.create(school=self.school, name="PG House")
        HouseholdAccess.objects.create(user=self.parent, household=self.house)
        self.app = get_or_create_annual_draft(
            user=self.parent, school_id=self.school.pk,
            household_id=self.house.pk, academic_year_id=self.year.pk,
        )
        self.storage = DisposableStore()
        self.doc = create_synthetic_document(
            user=self.parent, school_id=self.school.pk,
            household_id=self.house.pk, academic_year_id=self.year.pk,
            request_key=str(uuid.uuid4()), category="FICTIONAL_TAX",
            data=b"%PDF-1.7\nPG FAKE\n%%EOF",
            policy=SyntheticDocumentPolicy(
                version="fictional-policy",
                allowed_categories=("FICTIONAL_TAX",),
                allowed_media_types=("application/pdf",), maximum_bytes=4096,
            ),
            backend=self.storage,
        )

    def test_raw_identity_change_and_hard_delete_rejected(self):
        for attempt in (
            lambda: FinancialDocument.objects.filter(pk=self.doc.pk).update(
                household_id=uuid.uuid4()
            ),
            lambda: FinancialDocument.objects.filter(pk=self.doc.pk).delete(),
            lambda: FinancialDocumentEvent.objects.filter(document=self.doc).delete(),
        ):
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    attempt()
        self.assertEqual(FinancialDocument.objects.count(), 1)
        self.assertEqual(FinancialDocumentEvent.objects.count(), 1)
