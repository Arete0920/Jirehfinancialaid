"""Synthetic rotation contracts: two independent mailbox proofs and audit history."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.utils import timezone

from .models import (
    MailboxChallenge, PasswordRecoveryChallenge, RecoveryContactRotationEvent,
    VerifiedRecoveryContact,
)
from .password_recovery import (
    _prepare_recovery, enroll_verified_recovery_contact,
    reset_password_with_recovery, rotate_verified_recovery_contact,
)
from .redemption import issue_mailbox_challenge


PASSWORD = "A-Synthetic-Current-Password-012345!"
NEW_PASSWORD = "Another-Synthetic-Strong-Password-12345!"


class VerifiedRecoveryRotationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_user(
            username="rotate-owner", password=PASSWORD,
        )
        cls.stranger = User.objects.create_user(
            username="rotate-stranger", password=PASSWORD,
        )

    def enroll(self):
        _, code = issue_mailbox_challenge(
            user=self.owner, email="old@example.org",
        )
        return enroll_verified_recovery_contact(
            user=self.owner, email="old@example.org", mailbox_token=code,
        )

    def proofs(self, actor=None):
        user = actor or self.owner
        old, old_code = issue_mailbox_challenge(
            user=user, email="old@example.org",
        )
        new, new_code = issue_mailbox_challenge(
            user=user, email="new@example.org",
        )
        return (old, old_code), (new, new_code)

    def rotate(self, old_token, new_token, **overrides):
        args = {
            "user": self.owner,
            "current_password": PASSWORD,
            "old_mailbox_token": old_token,
            "new_email": "new@example.org",
            "new_mailbox_token": new_token,
        }
        args.update(overrides)
        return rotate_verified_recovery_contact(**args)

    def test_rotation_keeps_history_and_consumes_both_mailbox_proofs(self):
        original = self.enroll()
        (old_proof, old_code), (new_proof, new_code) = self.proofs()
        old_recovery_id, _, old_reset_code = _prepare_recovery(
            username="rotate-owner",
        )
        result = self.rotate(old_code, new_code)
        self.assertEqual(result.email, "new@example.org")
        self.assertEqual(result.user_id, self.owner.pk)
        original.refresh_from_db()
        old_proof.refresh_from_db()
        new_proof.refresh_from_db()
        self.assertIsNotNone(original.superseded_at)
        self.assertIsNotNone(old_proof.consumed_at)
        self.assertIsNotNone(new_proof.consumed_at)
        self.assertEqual(
            VerifiedRecoveryContact.objects.filter(
                user=self.owner, superseded_at__isnull=True,
            ).count(), 1,
        )
        self.assertEqual(VerifiedRecoveryContact.objects.count(), 2)
        event = RecoveryContactRotationEvent.objects.get()
        self.assertEqual(event.old_contact_id, original.pk)
        self.assertEqual(event.new_contact_id, result.pk)
        self.assertEqual(event.actor_id, self.owner.pk)
        self.assertEqual(event.user_id, self.owner.pk)
        old_challenge = PasswordRecoveryChallenge.objects.get(
            pk=old_recovery_id,
        )
        self.assertIsNotNone(old_challenge.consumed_at)
        self.assertIsNone(old_challenge.password_changed_at)
        with self.assertRaises(ValidationError):
            reset_password_with_recovery(
                username="rotate-owner", token=old_reset_code,
                new_password=NEW_PASSWORD,
            )
        # The next internal reset must target only the replacement contact.
        new_id, recipient, new_reset_code = _prepare_recovery(
            username="rotate-owner",
        )
        self.assertEqual(recipient, "new@example.org")
        self.assertNotEqual(new_id, old_recovery_id)
        self.assertNotEqual(new_reset_code, old_reset_code)

    def test_requires_current_password_and_two_distinct_valid_proofs(self):
        self.enroll()
        (_, old_code), (_, new_code) = self.proofs()
        attempts = (
            {"current_password": "incorrect"},
            {"old_mailbox_token": "a" * 64},
            {"new_mailbox_token": "b" * 64},
            {"new_mailbox_token": old_code},
            {"new_email": "old@example.org"},
            {"user": self.stranger},
        )
        for params in attempts:
            with self.subTest(params=tuple(params)):
                with self.assertRaises((
                    PermissionDenied, ValidationError,
                )):
                    self.rotate(old_code, new_code, **params)
        self.assertEqual(VerifiedRecoveryContact.objects.count(), 1)
        self.assertFalse(RecoveryContactRotationEvent.objects.exists())
        self.assertEqual(
            MailboxChallenge.objects.filter(
                user=self.owner, consumed_at__isnull=True,
            ).count(), 2,
        )

    def test_anonymous_identity_cannot_rotate(self):
        self.enroll()
        (_, old_code), (_, new_code) = self.proofs()
        with self.assertRaises(PermissionDenied):
            self.rotate(old_code, new_code, user=AnonymousUser())
        self.assertEqual(VerifiedRecoveryContact.objects.count(), 1)

    def test_expired_old_or_new_proof_fails_without_state_changes(self):
        original = self.enroll()
        (old_proof, old_code), (new_proof, new_code) = self.proofs()
        with patch(
            "jireh.schools.password_recovery.timezone.now",
            return_value=old_proof.expires_at + timedelta(seconds=1),
        ):
            with self.assertRaises(ValidationError):
                self.rotate(old_code, new_code)
        self.assertIsNone(
            VerifiedRecoveryContact.objects.get(pk=original.pk).superseded_at
        )
        self.assertFalse(RecoveryContactRotationEvent.objects.exists())

    def test_rotation_is_single_use_and_cannot_be_replayed(self):
        original = self.enroll()
        (_, old_code), (_, new_code) = self.proofs()
        replacement = self.rotate(old_code, new_code)
        with self.assertRaises((ValidationError, PermissionDenied)):
            self.rotate(old_code, new_code)
        self.assertEqual(RecoveryContactRotationEvent.objects.count(), 1)
        self.assertEqual(VerifiedRecoveryContact.objects.count(), 2)
        self.assertIsNone(
            VerifiedRecoveryContact.objects.get(pk=replacement.pk).superseded_at
        )

    def test_immutable_contact_identity_and_rotation_audit(self):
        original = self.enroll()
        (_, old_code), (_, new_code) = self.proofs()
        new = self.rotate(old_code, new_code)
        original.refresh_from_db()
        original.superseded_at = None
        with self.assertRaises(ValidationError):
            original.save()
        with self.assertRaises(ValidationError):
            new.delete()
        event = RecoveryContactRotationEvent.objects.get()
        event.actor = self.stranger
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            event.delete()

    def test_postgres_raw_updates_and_audit_delete_are_blocked(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL integrity guard required.")
        original = self.enroll()
        (_, old_code), (_, new_code) = self.proofs()
        new = self.rotate(old_code, new_code)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                VerifiedRecoveryContact.objects.filter(pk=original.pk).update(
                    superseded_at=None,
                )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                VerifiedRecoveryContact.objects.filter(pk=new.pk).update(
                    email="forged@example.org",
                )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RecoveryContactRotationEvent.objects.all().delete()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RecoveryContactRotationEvent.objects.all().update(
                    actor=self.stranger,
                )

    def test_postgres_raw_mismatched_audit_event_is_blocked(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL integrity guard required.")
        self.enroll()
        (_, old_code), (_, new_code) = self.proofs()
        new = self.rotate(old_code, new_code)
        event = RecoveryContactRotationEvent.objects.get()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RecoveryContactRotationEvent.objects.bulk_create([
                    RecoveryContactRotationEvent(
                        user=self.stranger,
                        actor=self.stranger,
                        old_contact=event.old_contact,
                        new_contact=new,
                    )
                ])
