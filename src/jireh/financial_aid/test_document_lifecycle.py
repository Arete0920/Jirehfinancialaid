"""Disposable scoped document lifecycle acceptance: never use customer bytes."""
import json
import os
import tempfile
import uuid
from pathlib import Path
from datetime import date
from unittest.mock import patch

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

    def test_assigned_recovery_operator_finishes_pending_deletion_after_revocation(self):
        from .document_lifecycle import recover_synthetic_document_deletion
        from .local_encrypted_backend import LocalEncryptedClamdBackend, LocalEncryptedDocumentDeleter

        operator = get_user_model().objects.create_user(username="document-recovery", is_staff=True)
        with tempfile.TemporaryDirectory() as directory, self.settings(
            JIREH_SYNTHETIC_DOCUMENTS_ONLY=True,
            JIREH_SYNTHETIC_DOCUMENT_RECOVERY_ASSIGNMENTS=((operator.pk, self.school.pk),),
        ):
            class CleanScanner:
                def scan(self, data):
                    return True

            storage = LocalEncryptedClamdBackend(
                root=directory, encryption_key=os.urandom(32), scanner=CleanScanner(),
            )
            doc = create_synthetic_document(**self.params(backend=storage))
            with patch.object(storage, "delete", side_effect=OSError("fictional failure")):
                with self.assertRaisesRegex(DocumentLifecycleError, "document_storage_delete_failed"):
                    delete_synthetic_document(**self.scope(backend=storage), document_id=doc.pk)
            HouseholdAccess.objects.filter(user=self.user, household=self.house).update(is_active=False)
            with self.assertRaises(Http404):
                delete_synthetic_document(**self.scope(backend=storage), document_id=doc.pk)
            with self.assertRaises(Http404):
                read_synthetic_document(**self.scope(backend=storage), document_id=doc.pk)

            deleter = LocalEncryptedDocumentDeleter(root=directory)
            params = dict(operator=operator, school_id=self.school.pk, document_id=doc.pk, backend=deleter)
            with self.settings(JIREH_SYNTHETIC_DOCUMENT_RECOVERY_ASSIGNMENTS=((operator.pk, self.other_school.pk),)):
                with self.assertRaises(Http404):
                    recover_synthetic_document_deletion(**{**params, "school_id": self.other_school.pk})
            self.assertEqual(len(list(Path(directory).iterdir())), 1)
            self.assertFalse(doc.events.filter(action=FinancialDocumentEvent.ACTION_DELETED).exists())

            with patch.object(deleter, "delete", side_effect=OSError("fictional failure")):
                with self.assertRaisesRegex(DocumentLifecycleError, "document_storage_delete_failed"):
                    recover_synthetic_document_deletion(**params)
            doc.refresh_from_db()
            self.assertEqual(doc.state, FinancialDocument.STATE_DELETE_PENDING)
            self.assertFalse(doc.events.filter(action=FinancialDocumentEvent.ACTION_DELETED).exists())
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

            # The first failure follows unlink. The next attempt sees no file
            # but must still sync the directory before confirming removal.
            with patch("jireh.financial_aid.local_encrypted_backend.os.fsync", side_effect=OSError):
                for _ in range(2):
                    with self.assertRaisesRegex(DocumentLifecycleError, "document_storage_delete_failed"):
                        recover_synthetic_document_deletion(**params)
            doc.refresh_from_db()
            self.assertEqual(doc.state, FinancialDocument.STATE_DELETE_PENDING)
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertFalse(doc.events.filter(action=FinancialDocumentEvent.ACTION_DELETED).exists())

            with patch.object(FinancialDocumentEvent.objects, "create", side_effect=IntegrityError("audit failed")):
                with self.assertRaises(IntegrityError):
                    recover_synthetic_document_deletion(**params)
            doc.refresh_from_db()
            self.assertEqual(doc.state, FinancialDocument.STATE_DELETE_PENDING)
            self.assertEqual(list(Path(directory).iterdir()), [])

            recover_synthetic_document_deletion(**params)
            with patch.object(deleter, "delete", side_effect=AssertionError("unexpected retry")) as delete:
                recover_synthetic_document_deletion(**params)
                delete.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])
            doc.refresh_from_db()
            self.assertEqual(doc.state, FinancialDocument.STATE_DELETED)
            self.assertIsNotNone(doc.deleted_at)
            self.assertEqual(doc.events.get(action=FinancialDocumentEvent.ACTION_DELETED).actor_user_id, operator.pk)

    def test_recovery_cannot_start_a_deletion_or_cross_school_boundaries(self):
        from .document_lifecycle import recover_synthetic_document_deletion
        from .local_encrypted_backend import LocalEncryptedDocumentDeleter

        operator = get_user_model().objects.create_user(username="document-recovery", is_staff=True)
        doc = create_synthetic_document(**self.params())
        with tempfile.TemporaryDirectory() as directory:
            deleter = LocalEncryptedDocumentDeleter(root=directory)
            params = dict(operator=operator, school_id=self.school.pk, document_id=doc.pk, backend=deleter)
            with self.assertRaises(PermissionDenied):
                recover_synthetic_document_deletion(**params)
            with self.settings(JIREH_SYNTHETIC_DOCUMENT_RECOVERY_ASSIGNMENTS=((operator.pk, self.other_school.pk),)):
                with self.assertRaises(PermissionDenied):
                    recover_synthetic_document_deletion(**params)
                with self.assertRaises(Http404):
                    recover_synthetic_document_deletion(**{**params, "school_id": self.other_school.pk})
            with self.settings(JIREH_SYNTHETIC_DOCUMENT_RECOVERY_ASSIGNMENTS=((operator.pk, self.school.pk),)):
                with self.settings(JIREH_SYNTHETIC_DOCUMENTS_ONLY=False):
                    with self.assertRaises(PermissionDenied):
                        recover_synthetic_document_deletion(**params)
                with self.assertRaises(Http404):
                    recover_synthetic_document_deletion(**params)
                get_user_model().objects.filter(pk=operator.pk).update(is_active=False)
                with self.assertRaises(PermissionDenied):
                    recover_synthetic_document_deletion(**params)
        doc.refresh_from_db()
        self.assertEqual(doc.state, FinancialDocument.STATE_ACTIVE)
        self.assertEqual(doc.events.count(), 1)

    def test_delete_only_adapter_rejects_replaced_storage_root(self):
        from .local_encrypted_backend import LocalEncryptedDocumentDeleter, PrivateDocumentStorageError

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "storage"
            root.mkdir(mode=0o700)
            original = root.stat()
            deleter = LocalEncryptedDocumentDeleter(
                root=root, root_identity=(original.st_dev, original.st_ino),
            )
            root.rename(Path(directory) / "original")
            root.mkdir(mode=0o700)
            object_key = uuid.uuid4()
            replacement_file = root / f"{object_key.hex}.jenc"
            replacement_file.write_bytes(b"disposable replacement file")

            with self.assertRaisesRegex(PrivateDocumentStorageError, "private_storage_root_changed"):
                deleter.delete(str(object_key))
            self.assertTrue(replacement_file.exists())

    def test_storage_worker_requires_private_storage_launch_configuration(self):
        from scripts.run_synthetic_document_recovery_storage import _read_launch_config

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "launch.json"
            config = {
                "role": "jireh_storage_fixture", "password": "synthetic-test-password",
                "root": directory, "device": 1, "inode": 2,
                "claim": "jireh_recovery_claim_fixture", "confirm": "jireh_recovery_confirm_fixture",
            }
            config_path.write_text(json.dumps(config), encoding="utf-8")
            config_path.chmod(0o644)
            with config_path.open("rb") as launch_config:
                with self.assertRaisesRegex(ValueError, "Private launch configuration required"):
                    _read_launch_config(launch_config)
            config_path.chmod(0o600)
            with config_path.open("rb") as launch_config:
                self.assertEqual(_read_launch_config(launch_config), config)
            config["role"] = "jireh_worker_fixture"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with config_path.open("rb") as launch_config:
                with self.assertRaisesRegex(ValueError, "Invalid launch configuration"):
                    _read_launch_config(launch_config)

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

    def test_versioned_recovery_provisioning_separates_and_removes_grants(self):
        from scripts.provision_synthetic_document_recovery import provision_recovery_v1

        operator = get_user_model().objects.create_user(username="synthetic-storage-operator", is_staff=True)
        assigned = {"school_id": self.school.pk, "operator_id": operator.pk}
        with connection.cursor() as cursor:
            cursor.execute("GRANT CREATE ON SCHEMA public TO PUBLIC")
        try:
            with self.assertRaisesRegex(ValueError, "schema privileges rejected"):
                with provision_recovery_v1(connection.connection, **assigned):
                    self.fail("Unsafe public schema should reject provisioning")
        finally:
            with connection.cursor() as cursor:
                cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")

        with connection.cursor() as cursor:
            cursor.execute("GRANT UPDATE (action) ON public.financial_aid_financialdocumentevent TO PUBLIC")
        try:
            with self.assertRaisesRegex(ValueError, "Direct recovery table privileges rejected"):
                with provision_recovery_v1(connection.connection, **assigned):
                    self.fail("Direct audit access should reject provisioning")
        finally:
            with connection.cursor() as cursor:
                cursor.execute("REVOKE UPDATE (action) ON public.financial_aid_financialdocumentevent FROM PUBLIC")

        with provision_recovery_v1(connection.connection, **assigned) as roles:
            self.assertTrue(roles.claim.startswith("jireh_recovery_claim_v1_"))
            self.assertNotIn(roles.storage_password, repr(roles))
            self.assertNotIn(roles.operator_password, repr(roles))
            with connection.cursor() as cursor:
                for role, function, allowed in (
                    (roles.operator_role, roles.claim, False),
                    (roles.operator_role, roles.confirm, False),
                    (roles.operator_role, roles.finish, True),
                    (roles.storage_role, roles.claim, True),
                    (roles.storage_role, roles.confirm, True),
                    (roles.storage_role, roles.finish, False),
                ):
                    cursor.execute("SELECT pg_catalog.has_function_privilege(%s, %s, 'EXECUTE')",
                                   (role, f"public.{function}(uuid,uuid)"))
                    self.assertEqual(cursor.fetchone(), (allowed,))
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regrole(%s), to_regrole(%s), to_regclass(%s), to_regprocedure(%s)",
                           (roles.operator_role, roles.storage_role, f"public.{roles.receipts}",
                            f"public.{roles.finish}(uuid,uuid)"))
            self.assertEqual(cursor.fetchone(), (None, None, None, None))
