"""Regression evidence for disposable, non-provisioning school setup receipts."""

import hashlib
import os
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


def proposal(key, **changes):
    return {
        "code": "synthetic-setup-school",
        "name": "Synthetic Setup Academy",
        "timezone": "America/New_York",
        "idempotency_key": str(key),
        **changes,
    }


def expected_digest(key):
    # Independent fixed-format vector: do not call the production helper
    # to calculate the test's expected value.
    data = (
        '["jireh.school-setup-intent.v1","synthetic-setup-school",'
        '"Synthetic Setup Academy","America/New_York","' + str(key) + '"]'
    ).encode("ascii")
    return hashlib.sha256(data).hexdigest()


def record(operator, key, **changes):
    return record_synthetic_setup_intent(
        operator=operator, payload=proposal(key, **changes),
    )


@override_settings(**TEST_FLAGS)
class SetupIntentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.operator = operator_fixture()
        cls.other = get_user_model().objects.create_user(
            username="other-fixture-staff", is_staff=True,
        )

    def test_fixture_authorization_context(self):
        from django.conf import settings
        from .demo_platform_operations import _authorized_operator
        from .demo_setup_intents import _TEST_SETTINGS

        startup_module = os.environ.get("DJANGO_SETTINGS_MODULE")
        self.assertIn(startup_module, _TEST_SETTINGS)
        self.assertIn(settings.SETTINGS_MODULE, (None, startup_module))
        self.assertIs(settings.JIREH_SYNTHETIC_SETUP_INTENT_ONLY, True)
        self.assertEqual(settings.ROOT_URLCONF, "jireh.schools.demo_urls")
        self.assertIs(settings.JIREH_SYNTHETIC_SUBMISSION_ONLY, True)
        self.assertIsInstance(self.operator, get_user_model())
        self.assertTrue(self.operator.is_authenticated)
        self.assertTrue(self.operator.is_active)
        self.assertTrue(self.operator.is_staff)
        self.assertFalse(self.operator.is_superuser)
        self.assertEqual(self.operator.username, DEMO_OPERATOR)
        self.assertTrue(_authorized_operator(self.operator))

    def test_exact_replay_returns_original_immutable_receipt(self):
        key = uuid4()
        first = record(self.operator, key)
        second = record(self.operator, key)
        self.assertEqual(first.pk, second.pk)
        first.refresh_from_db()
        self.assertEqual(first.proposed_by_id, self.operator.pk)
        self.assertEqual(first.candidate_digest, expected_digest(key))
        self.assertEqual(first.idempotency_key, key)
        self.assertEqual(first.created_at, second.created_at)
        self.assertEqual(SchoolSetupIntent.objects.count(), 1)
        self.assertFalse(School.objects.exists())
        self.assertFalse(AcademicYear.objects.exists())
        self.assertFalse(SchoolStaffAccess.objects.exists())

    def test_changed_candidate_or_other_owner_cannot_replay(self):
        key = uuid4()
        record(self.operator, key)
        for changes in (
            {"code": "synthetic-other-school"},
            {"name": "Synthetic Other Academy"},
            {"timezone": "America/Chicago"},
        ):
            with self.subTest(changes=changes), self.assertRaises(PermissionDenied):
                record(self.operator, key, **changes)
        other_key = uuid4()
        # Direct fixture insert represents a key already owned by another
        # actor. The rehearsal must neither disclose nor rebind its receipt.
        SchoolSetupIntent.objects.create(
            proposed_by=self.other, idempotency_key=other_key,
            candidate_digest=expected_digest(other_key),
        )
        with self.assertRaises(PermissionDenied):
            record(self.operator, other_key)
        self.assertEqual(SchoolSetupIntent.objects.count(), 2)
        self.assertEqual(
            SchoolSetupIntent.objects.get(idempotency_key=key).candidate_digest,
            expected_digest(key),
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
        with patch.dict(os.environ, {"DJANGO_SETTINGS_MODULE": "jireh.runtime.settings"}):
            with self.assertRaises(PermissionDenied):
                record(self.operator, uuid4())
        self.assertFalse(SchoolSetupIntent.objects.exists())

    def test_malformed_candidate_or_caller_fingerprint_denied(self):
        key = uuid4()
        for invalid in (
            str(UUID(int=0)), key, str(key).upper(), key.hex, None,
        ):
            with self.subTest(key=invalid), self.assertRaises(ValidationError):
                record(self.operator, key, idempotency_key=invalid)
        for data in (
            None, [], {}, {"code": "synthetic-school"},
            proposal(key, code="Unsafe Code"),
            proposal(key, name="Leading space "),
            proposal(key, candidate_digest=expected_digest(key)),
            proposal(key, is_active=True),
            proposal(key, payment_provider="fictional"),
        ):
            with self.subTest(payload=data), self.assertRaises(ValidationError):
                record_synthetic_setup_intent(operator=self.operator, payload=data)
        self.assertFalse(SchoolSetupIntent.objects.exists())

    def test_unknown_or_unavailable_timezone_denied(self):
        with self.assertRaises(ValidationError):
            record(self.operator, uuid4(), timezone="America/Not_A_Zone")
        with patch("jireh.schools.demo_setup_intents.available_timezones",
                   return_value=set()):
            with self.assertRaises(ValidationError):
                record(self.operator, uuid4())
        self.assertFalse(SchoolSetupIntent.objects.exists())

    def test_versioned_digest_is_independent_of_payload_key_order(self):
        key = UUID("123e4567-e89b-42d3-a456-426614174000")
        original = record(self.operator, key)
        reordered = dict(reversed(list(proposal(key).items())))
        replay = record_synthetic_setup_intent(operator=self.operator, payload=reordered)
        self.assertEqual(original.pk, replay.pk)
        self.assertEqual(replay.candidate_digest, expected_digest(key))
        self.assertEqual(SchoolSetupIntent.objects.count(), 1)

    def test_new_request_key_changes_fingerprint(self):
        first = record(self.operator, uuid4())
        second = record(self.operator, uuid4())
        self.assertNotEqual(first.candidate_digest, second.candidate_digest)
        self.assertEqual(SchoolSetupIntent.objects.count(), 2)
        self.assertFalse(School.objects.exists())

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
        self.assertEqual(receipt.candidate_digest, expected_digest(receipt.idempotency_key))

    @skipUnlessDBFeature("has_select_for_update")
    def test_postgresql_direct_update_and_delete_denied(self):
        receipt = record(self.operator, uuid4())
        queryset = SchoolSetupIntent.objects.filter(pk=receipt.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            queryset.update(candidate_digest=OTHER_DIGEST)
        with self.assertRaises(IntegrityError), transaction.atomic():
            queryset.delete()
        self.assertEqual(queryset.get().candidate_digest, expected_digest(receipt.idempotency_key))

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
