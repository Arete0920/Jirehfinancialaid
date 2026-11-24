"""Disposable PostgreSQL/SQLite preparation-job lifecycle acceptance."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import UUID, uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, IntegrityError, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature

from .demo_preparation_jobs import advance_synthetic_preparation
from .demo_seed import DEMO_OPERATOR
from .demo_setup_intents import record_synthetic_setup_intent
from .models import (
    AcademicYear, School, SchoolPreparationEvent, SchoolSetupIntent,
    SchoolStaffAccess,
)


FLAGS = {
    "ROOT_URLCONF": "jireh.schools.demo_urls",
    "JIREH_SYNTHETIC_SUBMISSION_ONLY": True,
    "JIREH_SYNTHETIC_SETUP_INTENT_ONLY": True,
    "JIREH_SYNTHETIC_PREPARATION_JOB_ONLY": True,
}


def fixture():
    operator = get_user_model().objects.create_user(
        username=DEMO_OPERATOR, is_staff=True,
    )
    payload = {
        "code": "synthetic-preparation-school",
        "name": "Synthetic Preparation Academy",
        "timezone": "America/New_York",
        "idempotency_key": str(uuid4()),
    }
    return operator, payload


def command(operator, payload, action, key=None):
    return advance_synthetic_preparation(
        operator=operator, payload=payload, command=action,
        request_key=uuid4() if key is None else key,
    )


@override_settings(**FLAGS)
class PreparationJobTests(TestCase):
    def setUp(self):
        self.operator, self.payload = fixture()
        self.intent = record_synthetic_setup_intent(
            operator=self.operator, payload=self.payload,
        )

    def execute(self, action, key=None, **changes):
        return command(self.operator, {**self.payload, **changes}, action, key)

    def history(self):
        return list(self.intent.preparation_events.order_by("sequence"))

    def assert_no_provisioning(self):
        self.assertFalse(School.objects.filter(is_active=True).exists())
        self.assertFalse(AcademicYear.objects.exists())
        self.assertFalse(SchoolStaffAccess.objects.exists())

    def conflict(self):
        return School.objects.create(
            code=self.payload["code"], name="Existing fictional school",
            is_active=False,
        )

    def test_queue_run_and_exact_replay(self):
        queue_key, run_key = uuid4(), uuid4()
        queued = self.execute("QUEUE", queue_key)
        self.assertEqual(queued.action, "QUEUED")
        prepared = self.execute("RUN", run_key)
        self.assertEqual(prepared.action, "PREPARED")
        self.assertEqual(self.execute("QUEUE", queue_key).pk, queued.pk)
        self.assertEqual(self.execute("RUN", run_key).pk, prepared.pk)
        history = self.history()
        self.assertEqual([e.action for e in history], ["QUEUED", "STARTED", "PREPARED"])
        self.assertEqual([e.sequence for e in history], [1, 2, 3])
        self.assertTrue(all(e.actor_id == self.operator.pk for e in history))
        self.assertEqual([e.request_key for e in history], [queue_key, run_key, run_key])
        self.assertFalse(School.objects.exists())
        self.assert_no_provisioning()

    def test_no_implicit_queue_run_or_retry(self):
        with self.assertRaises(ValidationError):
            self.execute("RUN")
        queue_key = uuid4()
        self.execute("QUEUE", queue_key)
        with self.assertRaises(PermissionDenied):
            self.execute("RUN", queue_key)
        for action in ("QUEUE", "RETRY"):
            with self.subTest(action=action), self.assertRaises(ValidationError):
                self.execute(action)
        self.execute("RUN")
        for action in ("QUEUE", "RUN", "RETRY"):
            with self.subTest(action=action), self.assertRaises(ValidationError):
                self.execute(action)
        self.assertEqual(len(self.history()), 3)

    def test_retry_requires_cleared_conflict_and_is_bounded(self):
        self.execute("QUEUE")
        for attempt in range(1, 4):
            existing = self.conflict()
            failed = self.execute("RUN")
            self.assertEqual((failed.action, failed.attempt, failed.reason),
                             ("FAILED", attempt, "SCHOOL_CODE_CONFLICT"))
            with self.assertRaises(ValidationError):
                self.execute("RUN")
            with self.assertRaises(ValidationError):
                self.execute("RETRY")
            existing.refresh_from_db()
            self.assertFalse(existing.is_active)
            existing.delete()
            if attempt < 3:
                retry_key = uuid4()
                retried = self.execute("RETRY", retry_key)
                self.assertEqual((retried.action, retried.attempt),
                                 ("REQUEUED", attempt + 1))
                self.assertEqual(self.execute("RETRY", retry_key).pk, retried.pk)
                with self.assertRaises(ValidationError):
                    self.execute("RETRY")
            else:
                with self.assertRaises(ValidationError):
                    self.execute("RETRY")
        self.assertEqual(len(self.history()), 9)
        self.assert_no_provisioning()

    def test_successful_retry_preserves_failed_attempt(self):
        self.execute("QUEUE")
        existing = self.conflict()
        failure = self.execute("RUN")
        existing.delete()
        self.execute("RETRY")
        self.assertEqual(self.execute("RUN").action, "PREPARED")
        self.assertEqual([e.action for e in self.history()],
                         ["QUEUED", "STARTED", "FAILED", "REQUEUED", "STARTED", "PREPARED"])
        failure.refresh_from_db()
        self.assertEqual(failure.reason, "SCHOOL_CODE_CONFLICT")
        self.assertFalse(School.objects.exists())

    def test_changed_payload_unknown_receipt_wrong_actor_and_revocation_denied(self):
        for changes in (
            {"name": "Changed School"}, {"code": "different-code"},
            {"timezone": "America/Chicago"}, {"idempotency_key": str(uuid4())},
        ):
            with self.subTest(changes=changes), self.assertRaises(PermissionDenied):
                self.execute("QUEUE", **changes)
        other = get_user_model().objects.create_user(
            username="other-preparation-operator", is_staff=True,
        )
        with self.assertRaises(PermissionDenied):
            command(other, self.payload, "QUEUE")
        get_user_model().objects.filter(pk=self.operator.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            self.execute("QUEUE")
        self.assertFalse(SchoolPreparationEvent.objects.exists())

    def test_runtime_disabled_and_invalid_command_denied(self):
        with override_settings(JIREH_SYNTHETIC_PREPARATION_JOB_ONLY=False):
            with self.assertRaises(PermissionDenied):
                self.execute("QUEUE")
        with override_settings(ROOT_URLCONF="jireh.runtime.urls"):
            with self.assertRaises(PermissionDenied):
                self.execute("QUEUE")
        with patch.dict(os.environ, {"DJANGO_SETTINGS_MODULE": "jireh.runtime.settings"}):
            with self.assertRaises(PermissionDenied):
                self.execute("QUEUE")
        for action in ("ACTIVATE", "PROVISION", None, []):
            with self.subTest(action=action), self.assertRaises(ValidationError):
                self.execute(action)
        for key in (UUID(int=0), str(uuid4())):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                self.execute("QUEUE", key)
        self.assertFalse(SchoolPreparationEvent.objects.exists())

    def test_failed_audit_write_rolls_back_entire_run(self):
        self.execute("QUEUE")
        original = SchoolPreparationEvent.objects.create

        def fail_terminal(**kwargs):
            if kwargs["action"] == "PREPARED":
                raise DatabaseError("fictional audit failure")
            return original(**kwargs)

        with patch.object(SchoolPreparationEvent.objects, "create", side_effect=fail_terminal):
            with self.assertRaises(PermissionDenied):
                self.execute("RUN")
        self.assertEqual([e.action for e in self.history()], ["QUEUED"])
        self.assertFalse(School.objects.exists())

    def test_incomplete_and_corrupt_history_fail_closed(self):
        self.execute("QUEUE")
        SchoolPreparationEvent.objects.create(
            intent=self.intent, actor=self.operator, request_key=uuid4(),
            sequence=2, attempt=1, action="STARTED",
        )
        with self.assertRaises(PermissionDenied):
            self.execute("RUN")
        # A forged jump to the next attempt also fails history validation.
        SchoolPreparationEvent.objects.create(
            intent=self.intent, actor=self.operator, request_key=uuid4(),
            sequence=3, attempt=2, action="REQUEUED", reason="CODE_CONFLICT_RECHECK",
        )
        with self.assertRaises(PermissionDenied):
            self.execute("RETRY")
        self.assertEqual(len(self.history()), 3)

    def test_immutable_orm_and_database_bounds(self):
        queued = self.execute("QUEUE")
        queued.sequence = 2
        with self.assertRaises(ValidationError):
            queued.save()
        with self.assertRaises(ValidationError):
            queued.delete()
        for sequence, attempt, key, action, reason in (
            (1, 1, uuid4(), "STARTED", ""),
            (2, 4, uuid4(), "STARTED", ""),
            (2, 1, UUID(int=0), "STARTED", ""),
            (2, 1, uuid4(), "PREPARED", "arbitrary"),
        ):
            with self.subTest(sequence=sequence, attempt=attempt, action=action):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    SchoolPreparationEvent.objects.bulk_create([
                        SchoolPreparationEvent(
                            intent=self.intent, actor=self.operator, sequence=sequence,
                            attempt=attempt, request_key=key, action=action, reason=reason,
                        )
                    ])
        self.assertEqual(len(self.history()), 1)

    @skipUnlessDBFeature("has_select_for_update")
    def test_postgres_direct_update_and_delete_denied(self):
        queued = self.execute("QUEUE")
        evidence = SchoolPreparationEvent.objects.filter(pk=queued.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            evidence.update(action="STARTED")
        with self.assertRaises(IntegrityError), transaction.atomic():
            evidence.delete()
        self.assertEqual(evidence.get().action, "QUEUED")


@override_settings(**FLAGS)
class ConcurrentPreparationJobTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_parallel_exact_run_requests_commit_one_attempt(self):
        operator, payload = fixture()
        intent = record_synthetic_setup_intent(operator=operator, payload=payload)
        command(operator, payload, "QUEUE")
        request_key = uuid4()
        barrier = Barrier(2)

        def run():
            try:
                fresh = get_user_model().objects.get(pk=operator.pk)
                barrier.wait(timeout=10)
                return command(fresh, payload, "RUN", request_key).pk
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            first, second = executor.submit(run), executor.submit(run)
            self.assertEqual(first.result(timeout=20), second.result(timeout=20))
        self.assertEqual(list(intent.preparation_events.order_by("sequence").values_list(
            "action", flat=True,
        )), ["QUEUED", "STARTED", "PREPARED"])
        self.assertEqual(SchoolSetupIntent.objects.count(), 1)
        self.assertFalse(School.objects.exists())
