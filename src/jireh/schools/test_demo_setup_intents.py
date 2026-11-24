"""Regression evidence for disposable, non-provisioning school setup receipts."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import UUID, uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, IntegrityError, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature

from .demo_seed import DEMO_OPERATOR
from .demo_setup_intents import record_synthetic_setup_intent
from .models import AcademicYear, School, SchoolSetupIntent, SchoolStaffAccess


DEMO_DIGEST = hashlib.sha256(b"fictional school setup candidate A").hexdigest()
OTHER_DIGEST = hashlib.sha256(b"fictional school setup candidate B").hexdigest()
TEST_FLAGS = {
    "ROOT_URLCONF": "jireh.schools.demo_urls",
    "JIREH_SYNTHETIC_SUBMISSION_ONLY": True,
    "JIREH_SYNTHETIC_SETUP_INTENT_ONLY": True,
}


def operator_fixture():
    return get_user_model().objects.create_user(
        username=DEMO_OPERATOR, is_staff=True,
    )


def record(operator, key, digest=DEMO_DIGEST):
    return record_synthetic_setup_intent(
        operator=operator, idempotency_key=key, candidate_digest=digest,
    )


@override_settings(**TEST_FLAGS)
class SetupIntentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.operator = operator_fixture()
        cls.other = get_user_model().objects.create_user(
            username="other-fixture-staff", is_staff=True,
        )

    def test_exact_replay_returns_original_immutable_receipt(self):
        key = uuid4()
        first = record(self.operator, key)
        second = record(self.operator, key)
        self.assertEqual(first.pk, second.pk)
        first.refresh_from_db()
        self.assertEqual(first.proposed_by_id, self.operator.pk)
        self.assertEqual(first.candidate_digest, DEMO_DIGEST)
        self.assertEqual(first.idempotency_key, key)
        self.assertEqual(first.created_at, second.created_at)
        self.assertEqual(SchoolSetupIntent.objects.count(), 1)
        self.assertFalse(School.objects.exists())
        self.assertFalse(AcademicYear.objects.exists())
        self.assertFalse(SchoolStaffAccess.objects.exists())

    def test_changed_candidate_or_other_owner_cannot_replay(self):
        key = uuid4()
        record(self.operator, key)
        with self.assertRaises(PermissionDenied):
            record(self.operator, key, OTHER_DIGEST)
        other_key = uuid4()
        # Direct fixture insert represents a key already owned by another
        # actor. The rehearsal must neither disclose nor rebind its receipt.
        SchoolSetupIntent.objects.create(
            proposed_by=self.other, idempotency_key=other_key,
            candidate_digest=DEMO_DIGEST,
        )
        with self.assertRaises(PermissionDenied):
            record(self.operator, other_key)
        self.assertEqual(SchoolSetupIntent.objects.count(), 2)
        self.assertEqual(
            SchoolSetupIntent.objects.get(idempotency_key=key).candidate_digest,
            DEMO_DIGEST,
        )

    def test_nonfixture_and_stale_or_revoked_operator_denied(self):
        with self.assertRaises(PermissionDenied):
            record(self.other, uuid4())
        get_user_model().objects.filter(pk=self.operator.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            record(self.operator, uuid4())
        self.assertFalse(SchoolSetupIntent.objects.exists())

    def test_disabled_and_runtime_context_denied(self):
        with override_settings(JIREH_SYNTHETIC_SETUP_INTENT_ONLY=False):
            with self.assertRaises(PermissionDenied):
                record(self.operator, uuid4())
        with override_settings(ROOT_URLCONF="jireh.runtime.urls"):
            with self.assertRaises(PermissionDenied):
                record(self.operator, uuid4())
        with override_settings(SETTINGS_MODULE="jireh.runtime.settings"):
            with self.assertRaises(PermissionDenied):
                record(self.operator, uuid4())
        self.assertFalse(SchoolSetupIntent.objects.exists())

    def test_malformed_key_or_fingerprint_denied(self):
        for key in (UUID(int=0), str(uuid4()), None):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                record(self.operator, key)
        for digest in ("", DEMO_DIGEST.upper(), DEMO_DIGEST + "\n", "z" * 64, None):
            with self.subTest(digest=digest), self.assertRaises(ValidationError):
                record(self.operator, uuid4(), digest)
        self.assertFalse(SchoolSetupIntent.objects.exists())

    def test_persistence_failure_rolls_back_receipt(self):
        original = SchoolSetupIntent.objects.get_or_create

        def fail_after_insert(*args, **kwargs):
            original(*args, **kwargs)
            raise DatabaseError("synthetic storage failure")

        with patch.object(SchoolSetupIntent.objects, "get_or_create",
                          side_effect=fail_after_insert):
            with self.assertRaises(PermissionDenied):
                record(self.operator, uuid4())
        self.assertFalse(SchoolSetupIntent.objects.exists())
        self.assertFalse(School.objects.exists())

    def test_orm_update_and_delete_denied(self):
        receipt = record(self.operator, uuid4())
        receipt.candidate_digest = OTHER_DIGEST
        with self.assertRaises(ValidationError):
            receipt.save()
        with self.assertRaises(ValidationError):
            receipt.delete()
        receipt.refresh_from_db()
        self.assertEqual(receipt.candidate_digest, DEMO_DIGEST)

    @skipUnlessDBFeature("has_select_for_update")
    def test_postgresql_direct_update_and_delete_denied(self):
        receipt = record(self.operator, uuid4())
        queryset = SchoolSetupIntent.objects.filter(pk=receipt.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            queryset.update(candidate_digest=OTHER_DIGEST)
        with self.assertRaises(IntegrityError), transaction.atomic():
            queryset.delete()
        self.assertEqual(queryset.get().candidate_digest, DEMO_DIGEST)

    def test_database_rejects_duplicate_key_and_nil_key(self):
        receipt = record(self.operator, uuid4())
        # bulk_create deliberately bypasses the model's full_clean hook:
        # these must fail at the database constraint, not just Python.
        for key in (receipt.idempotency_key, UUID(int=0)):
            with self.subTest(key=key):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    SchoolSetupIntent.objects.bulk_create([
                        SchoolSetupIntent(
                            proposed_by=self.operator, idempotency_key=key,
                            candidate_digest=OTHER_DIGEST,
                        )
                    ])
        self.assertEqual(SchoolSetupIntent.objects.count(), 1)


@override_settings(**TEST_FLAGS)
class ParallelSetupIntentTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_parallel_exact_replays_commit_one_receipt(self):
        operator = operator_fixture()
        key = uuid4()
        barrier = Barrier(2)

        def submit():
            try:
                fresh = get_user_model().objects.get(pk=operator.pk)
                barrier.wait(timeout=10)
                return record(fresh, key).pk
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(submit)
            second = executor.submit(submit)
            self.assertEqual(first.result(timeout=20), second.result(timeout=20))
        self.assertEqual(SchoolSetupIntent.objects.filter(idempotency_key=key).count(), 1)
        self.assertFalse(School.objects.exists())
