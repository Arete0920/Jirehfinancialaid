"""Synthetic-only account-recovery contracts: no real SMTP transport or users."""

import hashlib
import re
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .delivery import DeliveryNotConfigured
from .models import (
    Household, HouseholdAccess, LoginAttemptBudget, MailboxChallenge,
    PasswordRecoveryChallenge, RecoveryAttemptBudget, School,
    VerifiedRecoveryContact,
)
from .password_recovery import (
    RECOVERY_LIFETIME, RECOVERY_MAX_ATTEMPTS, _charge,
    enroll_verified_recovery_contact, request_password_recovery,
    reset_password_with_recovery,
)
from .redemption import issue_mailbox_challenge
from .test_delivery import SMTP_SETTINGS


INITIAL = "Synthetic-Initial-Password-012345!"
CHANGED = "Another-Secure-Password-67990!"


@override_settings(
    **SMTP_SETTINGS,
    AUTH_PASSWORD_VALIDATORS=[
        {
            "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
            "OPTIONS": {"min_length": 12},
        },
        {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    ],
)
class VerifiedPasswordRecoveryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.parent = User.objects.create_user(
            username="recovery-parent", email="unverified@example.invalid",
            password=INITIAL,
        )
        cls.other = User.objects.create_user(
            username="recovery-other", email="family@example.org",
            password=INITIAL,
        )
        cls.school = School.objects.create(
            code="recovery-test", name="Recovery School",
        )
        cls.household = Household.objects.create(
            school=cls.school, name="Recovery Household",
        )
        HouseholdAccess.objects.create(
            user=cls.parent, household=cls.household,
        )

    def enroll(self, user=None, email="family@example.org"):
        owner = user or self.parent
        proof, secret = issue_mailbox_challenge(user=owner, email=email)
        contact = enroll_verified_recovery_contact(
            user=owner, email=email, mailbox_token=secret,
        )
        return contact, proof, secret

    @staticmethod
    def send_capture(messages):
        def send(message, fail_silently=False):
            messages.append({
                "to": tuple(message.to),
                "subject": message.subject,
                "body": message.body,
            })
            return 1
        return send

    def request_code(self, username="recovery-parent"):
        messages = []
        with patch(
            "jireh.schools.delivery.EmailMessage.send",
            autospec=True,
            side_effect=self.send_capture(messages),
        ):
            response = request_password_recovery(username=username)
        return response, messages

    @staticmethod
    def code(message):
        found = re.search(r"\n\n([A-Za-z0-9_-]{64})\n\n", message["body"])
        if found is None:
            raise AssertionError("No synthetic one-time code found.")
        return found.group(1)

    def household_url(self):
        return reverse(
            "jireh_household_detail",
            kwargs={
                "school_id": self.school.pk,
                "household_id": self.household.pk,
            },
        )

    def test_recovery_requires_prior_proof_not_user_email(self):
        self.parent.email = "family@example.org"
        self.parent.save(update_fields=["email"])
        accepted, messages = self.request_code()
        self.assertEqual(accepted, {"accepted": True})
        self.assertEqual(messages, [])
        self.assertFalse(PasswordRecoveryChallenge.objects.exists())
        self.assertEqual(RecoveryAttemptBudget.objects.count(), 1)

    def test_unknown_and_unverified_accounts_are_indistinguishable(self):
        first, sent1 = self.request_code("missing-account")
        second, sent2 = self.request_code()
        self.assertEqual(first, second)
        self.assertEqual(first, {"accepted": True})
        self.assertEqual(sent1, [])
        self.assertEqual(sent2, [])
        self.assertFalse(PasswordRecoveryChallenge.objects.exists())
        self.assertEqual(RecoveryAttemptBudget.objects.count(), 2)
        for row in RecoveryAttemptBudget.objects.all():
            self.assertEqual(len(row.identifier_digest), 64)
            self.assertNotIn("recovery", row.identifier_digest)

    def test_mailbox_proof_is_scoped_fresh_and_single_use(self):
        proof, secret = issue_mailbox_challenge(
            user=self.parent, email="family@example.org",
        )
        with self.assertRaises(ValidationError):
            enroll_verified_recovery_contact(
                user=self.other, email="family@example.org",
                mailbox_token=secret,
            )
        with self.assertRaises(ValidationError):
            enroll_verified_recovery_contact(
                user=self.parent, email="different@example.org",
                mailbox_token=secret,
            )
        with self.assertRaises(PermissionDenied):
            enroll_verified_recovery_contact(
                user=AnonymousUser(), email="family@example.org",
                mailbox_token=secret,
            )
        contact = enroll_verified_recovery_contact(
            user=self.parent, email="family@example.org",
            mailbox_token=secret,
        )
        self.assertEqual(contact.proof_id, proof.pk)
        self.assertEqual(contact.user_id, self.parent.pk)
        self.assertEqual(contact.email, "family@example.org")
        self.assertEqual(
            contact.verified_at,
            MailboxChallenge.objects.get(pk=proof.pk).consumed_at,
        )
        with self.assertRaises(ValidationError):
            enroll_verified_recovery_contact(
                user=self.parent, email="family@example.org",
                mailbox_token=secret,
            )
        with self.assertRaises(ValidationError):
            contact.delete()

    def test_expired_mailbox_proof_cannot_establish_contact(self):
        proof, secret = issue_mailbox_challenge(
            user=self.parent, email="family@example.org",
        )
        with patch(
            "jireh.schools.password_recovery.timezone.now",
            return_value=proof.expires_at + timedelta(seconds=1),
        ):
            with self.assertRaises(ValidationError):
                enroll_verified_recovery_contact(
                    user=self.parent, email="family@example.org",
                    mailbox_token=secret,
                )
        self.assertFalse(VerifiedRecoveryContact.objects.exists())
        self.assertIsNone(
            MailboxChallenge.objects.get(pk=proof.pk).consumed_at,
        )

    def test_disabled_transport_blocks_issuance_without_storing_code(self):
        self.enroll()
        with override_settings(JIREH_EMAIL_DELIVERY_ENABLED=False):
            with patch("jireh.schools.delivery.EmailMessage.send") as send:
                with self.assertRaises(DeliveryNotConfigured):
                    request_password_recovery(username="recovery-parent")
                send.assert_not_called()
        self.assertFalse(PasswordRecoveryChallenge.objects.exists())

    def test_only_verified_recipient_receives_recovery_secret(self):
        contact, proof, _ = self.enroll()
        accepted, messages = self.request_code()
        self.assertEqual(accepted, {"accepted": True})
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["to"], ("family@example.org",))
        self.assertNotIn("unverified@example.invalid", messages[0]["body"])
        secret = self.code(messages[0])
        self.assertNotIn(secret, str(PasswordRecoveryChallenge.objects.values()))
        challenge = PasswordRecoveryChallenge.objects.get()
        self.assertEqual(
            challenge.token_digest,
            hashlib.sha256(secret.encode("ascii")).hexdigest(),
        )
        self.assertEqual(challenge.contact_id, contact.pk)
        self.assertLessEqual(
            challenge.expires_at,
            timezone.now() + RECOVERY_LIFETIME + timedelta(seconds=5),
        )
        self.assertIsNone(challenge.consumed_at)

    def test_password_recovery_changes_hash_and_revokes_existing_sessions(self):
        self.enroll()
        client = Client(enforce_csrf_checks=False)
        client.force_login(self.parent)
        self.assertEqual(client.get(self.household_url()).status_code, 200)
        old_hash = get_user_model().objects.get(pk=self.parent.pk).password

        response, messages = self.request_code()
        secret = self.code(messages[0])
        changed = reset_password_with_recovery(
            username=self.parent.username, token=secret, new_password=CHANGED,
        )
        self.assertEqual(response, {"accepted": True})
        self.assertEqual(changed, {"password_changed": True})
        user = get_user_model().objects.get(pk=self.parent.pk)
        self.assertNotEqual(user.password, old_hash)
        self.assertTrue(user.check_password(CHANGED))
        self.assertFalse(user.check_password(INITIAL))
        self.assertEqual(client.get(self.household_url()).status_code, 403)
        challenge = PasswordRecoveryChallenge.objects.get()
        self.assertIsNotNone(challenge.consumed_at)
        self.assertEqual(
            challenge.password_changed_at, challenge.consumed_at,
        )
        with self.assertRaises(ValidationError):
            reset_password_with_recovery(
                username=self.parent.username, token=secret, new_password=INITIAL,
            )

    def test_wrong_account_token_and_expired_code_fail_without_password_change(self):
        self.enroll()
        _, emails = self.request_code()
        secret = self.code(emails[0])
        for username, token in (
            ("recovery-other", secret),
            ("recovery-parent", "a" * 64),
            ("missing-account", secret),
        ):
            with self.subTest(username=username):
                with self.assertRaises(ValidationError):
                    reset_password_with_recovery(
                        username=username, token=token, new_password=CHANGED,
                    )
        challenge = PasswordRecoveryChallenge.objects.get()
        with patch(
            "jireh.schools.password_recovery.timezone.now",
            return_value=challenge.expires_at + timedelta(seconds=1),
        ):
            with self.assertRaises(ValidationError):
                reset_password_with_recovery(
                    username="recovery-parent",
                    token=secret,
                    new_password=CHANGED,
                )
        self.assertTrue(
            get_user_model().objects.get(pk=self.parent.pk).check_password(INITIAL)
        )

    def test_weak_password_cannot_consume_valid_recovery_code(self):
        self.enroll()
        _, emails = self.request_code()
        secret = self.code(emails[0])
        with self.assertRaises(ValidationError):
            reset_password_with_recovery(
                username=self.parent.username, token=secret,
                new_password="short",
            )
        challenge = PasswordRecoveryChallenge.objects.get()
        self.assertIsNone(challenge.consumed_at)
        self.assertTrue(
            get_user_model().objects.get(pk=self.parent.pk).check_password(INITIAL)
        )

    def test_reissue_consumes_previous_code_and_old_code_fails(self):
        self.enroll()
        _, first = self.request_code()
        _, second = self.request_code()
        old = self.code(first[0])
        new = self.code(second[0])
        self.assertNotEqual(old, new)
        self.assertEqual(PasswordRecoveryChallenge.objects.count(), 2)
        with self.assertRaises(ValidationError):
            reset_password_with_recovery(
                username="recovery-parent", token=old, new_password=CHANGED,
            )
        reset_password_with_recovery(
            username="recovery-parent", token=new, new_password=CHANGED,
        )
        self.assertEqual(
            PasswordRecoveryChallenge.objects.filter(
                consumed_at__isnull=True,
            ).count(),
            0,
        )

    def test_failed_or_ambiguous_smtp_delivery_consumes_code(self):
        self.enroll()
        with patch(
            "jireh.schools.delivery.EmailMessage.send",
            side_effect=RuntimeError("secret provider diagnostic"),
        ):
            accepted = request_password_recovery(username="recovery-parent")
        self.assertEqual(accepted, {"accepted": True})
        self.assertIsNotNone(
            PasswordRecoveryChallenge.objects.get().consumed_at,
        )
        self.assertFalse(
            get_user_model().objects.get(pk=self.parent.pk).check_password(CHANGED)
        )

    def test_request_and_confirmation_limits_are_independent(self):
        self.enroll()
        for _ in range(RECOVERY_MAX_ATTEMPTS + 2):
            self.assertEqual(
                request_password_recovery(username="unknown-user"),
                {"accepted": True},
            )
        issue = RecoveryAttemptBudget.objects.get(
            purpose=RecoveryAttemptBudget.PURPOSE_ISSUE,
        )
        self.assertEqual(issue.attempt_count, 10)
        for _ in range(RECOVERY_MAX_ATTEMPTS):
            with self.assertRaises(ValidationError):
                reset_password_with_recovery(
                    username="unknown-user", token="a" * 64,
                    new_password=CHANGED,
                )
        with self.assertRaises(PermissionDenied):
            reset_password_with_recovery(
                username="unknown-user", token="a" * 64,
                new_password=CHANGED,
            )
        confirm = RecoveryAttemptBudget.objects.get(
            purpose=RecoveryAttemptBudget.PURPOSE_CONFIRM,
        )
        self.assertEqual(confirm.attempt_count, 10)
        # HMAC identifier is the same; the composite (digest, purpose) key
        # deliberately keeps the two independent budgets separate.
        self.assertEqual(confirm.identifier_digest, issue.identifier_digest)
        self.assertNotEqual(confirm.purpose, issue.purpose)

    def test_audit_rows_cannot_be_modified_via_model(self):
        self.enroll()
        _, messages = self.request_code()
        record = PasswordRecoveryChallenge.objects.get()
        record.token_digest = "b" * 64
        with self.assertRaises(ValidationError):
            record.save()
        with self.assertRaises(ValidationError):
            record.delete()

    def test_postgres_guard_rejects_raw_recovery_evidence_mutation(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL guard enforcement required.")
        self.enroll()
        _, messages = self.request_code()
        challenge = PasswordRecoveryChallenge.objects.get()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM pg_trigger WHERE tgname IN ("
                "'jireh_schools_verifiedrecoverycontact_protect', "
                "'jireh_schools_passwordrecoverychallenge_protect'"
                ") AND NOT tgisinternal"
            )
            self.assertEqual(cursor.fetchone()[0], 2)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PasswordRecoveryChallenge.objects.filter(
                    pk=challenge.pk,
                ).update(token_digest="c" * 64)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                VerifiedRecoveryContact.objects.all().update(
                    email="forged@example.org",
                )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PasswordRecoveryChallenge.objects.filter(
                    pk=challenge.pk,
                ).delete()
