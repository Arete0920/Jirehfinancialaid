"""Internal SMTP delivery: opt-in configuration, actor scope, failure cleanup.

No live SMTP traffic. All message transport is replaced with a test double.
"""

import re
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings
from django.http import Http404

from .delivery import (
    DeliveryFailure, DeliveryNotConfigured,
    deliver_household_invitation, deliver_mailbox_challenge,
)
from .models import (
    Household, HouseholdAccess, HouseholdInvitation,
    MailboxChallenge, School, SchoolInvitationEvent, SchoolStaffAccess,
)
from .redemption import redeem_household_invitation


SMTP_SETTINGS = {
    "JIREH_EMAIL_DELIVERY_ENABLED": True,
    "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
    "EMAIL_USE_TLS": True,
    "EMAIL_USE_SSL": False,
    "EMAIL_HOST": "smtp.example.invalid",
    "EMAIL_PORT": 587,
    "EMAIL_HOST_USER": "test-username",
    "EMAIL_HOST_PASSWORD": "test-password-not-used",
    "EMAIL_TIMEOUT": 5,
    "JIREH_EMAIL_FROM": "jireh@example.invalid",
}


class DeliveryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.director = User.objects.create_user(username="smtp-director")
        cls.other_director = User.objects.create_user(username="smtp-other-director")
        cls.parent = User.objects.create_user(username="smtp-parent")
        cls.other_parent = User.objects.create_user(username="smtp-other-parent")
        cls.school = School.objects.create(code="smtp-a", name="School A")
        cls.other_school = School.objects.create(code="smtp-b", name="School B")
        cls.household = Household.objects.create(
            school=cls.school, name="SMTP household"
        )
        cls.other_household = Household.objects.create(
            school=cls.other_school, name="Other SMTP household"
        )
        SchoolStaffAccess.objects.create(
            school=cls.school, user=cls.director,
            role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        )
        SchoolStaffAccess.objects.create(
            school=cls.other_school, user=cls.other_director,
            role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        )

    def invite(self, **changes):
        params = dict(
            actor=self.director, school_id=self.school.pk,
            household_id=self.household.pk, email=" FAMILY@EXAMPLE.ORG ",
        )
        params.update(changes)
        return deliver_household_invitation(**params)

    def mailbox(self, invitation_token, **changes):
        params = dict(
            user=self.parent, school_id=self.school.pk,
            household_id=self.household.pk, invitation_token=invitation_token,
        )
        params.update(changes)
        return deliver_mailbox_challenge(**params)

    @staticmethod
    def capture(seen):
        def _send(msg, fail_silently=False):
            seen.append({
                "to": msg.to[:],
                "subject": msg.subject,
                "body": msg.body,
                "sender": msg.from_email,
            })
            return 1
        return _send

    @staticmethod
    def code(msg):
        # Email secret is passed as a code in the body, never in the subject.
        found = re.search(r"\n\n([A-Za-z0-9_-]{64})\n\n", msg["body"])
        if not found:
            raise AssertionError("Test transport did not receive an opaque secret.")
        return found.group(1)

    def test_disabled_by_default_and_never_calls_transport(self):
        with patch("jireh.schools.delivery.EmailMessage.send") as send:
            with self.assertRaises(DeliveryNotConfigured):
                self.invite()
            with self.assertRaises(DeliveryNotConfigured):
                self.mailbox("x" * 64)
        send.assert_not_called()
        self.assertEqual(HouseholdInvitation.objects.count(), 0)
        self.assertEqual(MailboxChallenge.objects.count(), 0)

    @override_settings(**SMTP_SETTINGS)
    def test_successful_invitation_and_mailbox_proof_deliver_to_exact_address(self):
        seen = []
        with patch(
            "jireh.schools.delivery.EmailMessage.send",
            autospec=True,
            side_effect=self.capture(seen),
        ):
            invitation_id = self.invite()
        invitation = HouseholdInvitation.objects.get(pk=invitation_id)
        self.assertEqual(invitation.email, "family@example.org")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["to"], ["family@example.org"])
        self.assertEqual(seen[0]["sender"], "jireh@example.invalid")
        self.assertNotIn(self.code(seen[0]), str(invitation.token_digest))
        with patch(
            "jireh.schools.delivery.EmailMessage.send",
            autospec=True,
            side_effect=self.capture(seen),
        ):
            challenge_id = self.mailbox(self.code(seen[0]))
        proof = MailboxChallenge.objects.get(pk=challenge_id)
        self.assertEqual(proof.user_id, self.parent.pk)
        self.assertEqual(proof.email, "family@example.org")
        self.assertEqual(seen[1]["to"], ["family@example.org"])
        self.assertNotEqual(self.code(seen[0]), self.code(seen[1]))
        self.assertEqual(HouseholdAccess.objects.count(), 0)
        grant = redeem_household_invitation(
            user=self.parent, school_id=self.school.pk,
            household_id=self.household.pk,
            invitation_token=self.code(seen[0]),
            mailbox_token=self.code(seen[1]),
        )
        self.assertEqual(grant.user_id, self.parent.pk)
        self.assertEqual(grant.household_id, self.household.pk)
        self.assertEqual(HouseholdAccess.objects.count(), 1)

    @override_settings(**SMTP_SETTINGS)
    def test_invalid_transport_configuration_fails_before_creating_tokens(self):
        cases = (
            {"EMAIL_BACKEND": "django.core.mail.backends.console.EmailBackend"},
            {"EMAIL_USE_TLS": False},
            {"EMAIL_USE_SSL": True},
            {"EMAIL_PORT": 25},
            {"EMAIL_HOST": "localhost"},
            {"EMAIL_HOST_USER": ""},
            {"EMAIL_HOST_PASSWORD": ""},
            {"EMAIL_TIMEOUT": None},
            {"EMAIL_TIMEOUT": 11},
            {"JIREH_EMAIL_FROM": "not-an-email"},
            {"JIREH_EMAIL_DELIVERY_ENABLED": False},
        )
        for values in cases:
            with self.subTest(values=values):
                with override_settings(**values):
                    with patch("jireh.schools.delivery.EmailMessage.send") as send:
                        with self.assertRaises(DeliveryNotConfigured):
                            self.invite()
                        send.assert_not_called()
        self.assertEqual(HouseholdInvitation.objects.count(), 0)

    @override_settings(**SMTP_SETTINGS)
    def test_ssl_465_supported_with_authenticated_smtp(self):
        with override_settings(
            EMAIL_USE_TLS=False, EMAIL_USE_SSL=True, EMAIL_PORT=465
        ):
            with patch("jireh.schools.delivery.EmailMessage.send", return_value=1):
                invitation_id = self.invite()
        self.assertIsNotNone(invitation_id)

    @override_settings(**SMTP_SETTINGS)
    def test_failed_invitation_send_is_audited_and_revoked(self):
        with patch(
            "jireh.schools.delivery.EmailMessage.send",
            side_effect=RuntimeError("danger: provider echoed SECRET"),
        ):
            with self.assertRaises(DeliveryFailure) as caught:
                self.invite()
        self.assertNotIn("SECRET", str(caught.exception))
        invitation = HouseholdInvitation.objects.get()
        self.assertIsNotNone(invitation.revoked_at)
        self.assertIsNone(invitation.redeemed_at)
        self.assertEqual(
            set(
                SchoolInvitationEvent.objects.filter(
                    invitation=invitation
                ).values_list("action", flat=True)
            ),
            {"ISSUED", "REVOKED"},
        )
        self.assertEqual(HouseholdAccess.objects.count(), 0)

    @override_settings(**SMTP_SETTINGS)
    def test_send_returning_zero_revokes_invitation(self):
        with patch("jireh.schools.delivery.EmailMessage.send", return_value=0):
            with self.assertRaises(DeliveryFailure):
                self.invite()
        self.assertIsNotNone(HouseholdInvitation.objects.get().revoked_at)

    @override_settings(**SMTP_SETTINGS)
    def test_cancelled_invitation_can_be_reissued_safely(self):
        with patch("jireh.schools.delivery.EmailMessage.send", return_value=0):
            with self.assertRaises(DeliveryFailure):
                self.invite()
        with patch("jireh.schools.delivery.EmailMessage.send", return_value=1):
            second = self.invite()
        self.assertEqual(HouseholdInvitation.objects.count(), 2)
        self.assertIsNone(HouseholdInvitation.objects.get(pk=second).revoked_at)

    @override_settings(**SMTP_SETTINGS)
    def test_failed_mailbox_send_consumes_challenge_and_is_not_authorization(self):
        seen = []
        with patch(
            "jireh.schools.delivery.EmailMessage.send",
            autospec=True,
            side_effect=self.capture(seen),
        ):
            self.invite()
        with patch(
            "jireh.schools.delivery.EmailMessage.send",
            side_effect=RuntimeError("provider credentials in error"),
        ):
            with self.assertRaises(DeliveryFailure) as caught:
                self.mailbox(self.code(seen[0]))
        self.assertNotIn("credentials", str(caught.exception))
        proof = MailboxChallenge.objects.get()
        self.assertIsNotNone(proof.consumed_at)
        self.assertEqual(HouseholdAccess.objects.count(), 0)

    @override_settings(**SMTP_SETTINGS)
    def test_mailbox_send_returning_zero_consumes_challenge(self):
        seen = []
        with patch(
            "jireh.schools.delivery.EmailMessage.send",
            autospec=True,
            side_effect=self.capture(seen),
        ):
            self.invite()
        with patch("jireh.schools.delivery.EmailMessage.send", return_value=0):
            with self.assertRaises(DeliveryFailure):
                self.mailbox(self.code(seen[0]))
        self.assertIsNotNone(MailboxChallenge.objects.get().consumed_at)

    @override_settings(**SMTP_SETTINGS)
    def test_other_school_and_unauthorized_directors_cannot_send(self):
        with patch("jireh.schools.delivery.EmailMessage.send") as send:
            with self.assertRaises(Http404):
                self.invite(household_id=self.other_household.pk)
            with self.assertRaises(Http404):
                self.invite(actor=self.other_director)
            with self.assertRaises(PermissionDenied):
                self.invite(actor=AnonymousUser())
            send.assert_not_called()
        self.assertEqual(HouseholdInvitation.objects.count(), 0)

    @override_settings(**SMTP_SETTINGS)
    def test_mailbox_challenge_cannot_use_untrusted_recipient_or_scope(self):
        seen = []
        with patch(
            "jireh.schools.delivery.EmailMessage.send",
            autospec=True,
            side_effect=self.capture(seen),
        ):
            self.invite()
        with patch("jireh.schools.delivery.EmailMessage.send") as send:
            for scope in (
                {"school_id": self.other_school.pk},
                {"household_id": self.other_household.pk},
                {"user": AnonymousUser()},
                {"invitation_token": "a" * 64},
            ):
                with self.subTest(scope=scope):
                    expected = PermissionDenied if "user" in scope else Http404
                    with self.assertRaises(expected):
                        self.mailbox(self.code(seen[0]), **scope)
            send.assert_not_called()
        self.assertEqual(MailboxChallenge.objects.count(), 0)
