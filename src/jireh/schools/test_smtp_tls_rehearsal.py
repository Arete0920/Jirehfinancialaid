"""Exercise invitation delivery through the real Django SMTP client on loopback."""

import re
from email import policy
from email.parser import BytesParser

from django.http import Http404
from django.test import TransactionTestCase

from .delivery import DeliveryFailure, deliver_household_invitation, deliver_mailbox_challenge
from .demo_seed import seed_synthetic_browser_demo
from .models import HouseholdAccess, HouseholdInvitation, MailboxChallenge, SchoolInvitationEvent
from .redemption import redeem_household_invitation
from .smtp_test_mailbox import SMTP_SENDER, tls_mailbox


_RECIPIENT = "fictional-family@example.invalid"
_MAIL_CODE = re.compile(r"\n\n([A-Za-z0-9_-]{64})\n\n")
_DELIVERY_FAILURE = "Jireh email delivery was not confirmed."


class FictionalSmtpTlsRehearsalTests(TransactionTestCase):
    def setUp(self):
        demo = seed_synthetic_browser_demo(grant_family_access=False)
        self.director = demo["director_a"]
        self.parent = demo["parent"]
        self.scope = {
            "school_id": demo["school_a"].pk,
            "household_id": demo["household_a"].pk,
        }

    def _invite(self):
        return deliver_household_invitation(actor=self.director, email=_RECIPIENT, **self.scope)

    def _challenge(self, invitation_code):
        return deliver_mailbox_challenge(user=self.parent, invitation_token=invitation_code, **self.scope)

    def _code(self, delivery, subject):
        self.assertEqual(delivery.sender, SMTP_SENDER)
        self.assertEqual(delivery.recipient, _RECIPIENT)
        self.assertIn(delivery.tls_version, ("TLSv1.2", "TLSv1.3"))
        message = BytesParser(policy=policy.default).parsebytes(delivery.message)
        self.assertTrue(message["Subject"] == subject, "Unexpected synthetic message subject.")
        match = _MAIL_CODE.search(message.get_content().replace("\r\n", "\n"))
        self.assertIsNotNone(match, "Expected a code in the synthetic SMTP message.")
        return match.group(1)

    def _assert_sanitized_failure(self, error):
        self.assertTrue(str(error) == _DELIVERY_FAILURE, "Expected a sanitized SMTP error.")

    def _assert_invitation_revoked(self):
        invitation = HouseholdInvitation.objects.get()
        self.assertIsNotNone(invitation.revoked_at)
        self.assertIsNone(invitation.redeemed_at)
        actions = SchoolInvitationEvent.objects.filter(invitation=invitation).values_list(
            "action", "actor_user_id",
        )
        self.assertCountEqual(actions, [
            (SchoolInvitationEvent.ACTION_ISSUED, self.director.pk),
            (SchoolInvitationEvent.ACTION_REVOKED, self.director.pk),
        ])
        self.assertFalse(MailboxChallenge.objects.exists())
        self.assertFalse(HouseholdAccess.objects.exists())

    def test_authenticated_tls_delivery_supports_household_redemption(self):
        with tls_mailbox() as mailbox:
            invitation_id = self._invite()
            self.assertEqual(len(mailbox.deliveries), 1)
            invitation_code = self._code(mailbox.deliveries[0], "Jireh Financial Aid invitation")
            challenge_id = self._challenge(invitation_code)
            self.assertEqual(len(mailbox.deliveries), 2)
            mailbox_code = self._code(mailbox.deliveries[1], "Jireh Financial Aid email verification")

        self.assertTrue(invitation_code != mailbox_code, "Expected distinct two-proof codes.")
        self.assertFalse(HouseholdAccess.objects.exists())
        grant = redeem_household_invitation(
            user=self.parent, invitation_token=invitation_code, mailbox_token=mailbox_code,
            **self.scope,
        )
        self.assertEqual(grant.user_id, self.parent.pk)
        self.assertEqual(grant.household_id, self.scope["household_id"])
        self.assertIsNotNone(HouseholdInvitation.objects.get(pk=invitation_id).redeemed_at)
        self.assertIsNotNone(MailboxChallenge.objects.get(pk=challenge_id).consumed_at)

    def test_smtp_data_rejection_revokes_invitation_and_blocks_code(self):
        with tls_mailbox(reject_data=True) as mailbox:
            with self.assertRaises(DeliveryFailure) as failure:
                self._invite()
            self._assert_sanitized_failure(failure.exception)
            self.assertEqual(len(mailbox.deliveries), 1)
            invitation_code = self._code(mailbox.deliveries[0], "Jireh Financial Aid invitation")
            with self.assertRaises(Http404):
                self._challenge(invitation_code)
            self.assertEqual(len(mailbox.deliveries), 1)

        self._assert_invitation_revoked()

    def test_smtp_data_rejection_consumes_mailbox_code_and_blocks_redemption(self):
        with tls_mailbox() as mailbox:
            invitation_id = self._invite()
            invitation_code = self._code(mailbox.deliveries[0], "Jireh Financial Aid invitation")
            mailbox.reject_data = True
            with self.assertRaises(DeliveryFailure) as failure:
                self._challenge(invitation_code)
            self._assert_sanitized_failure(failure.exception)
            self.assertEqual(len(mailbox.deliveries), 2)
            mailbox_code = self._code(mailbox.deliveries[1], "Jireh Financial Aid email verification")

        self.assertIsNotNone(MailboxChallenge.objects.get().consumed_at)
        with self.assertRaises(Http404):
            redeem_household_invitation(
                user=self.parent, invitation_token=invitation_code, mailbox_token=mailbox_code,
                **self.scope,
            )
        invitation = HouseholdInvitation.objects.get(pk=invitation_id)
        self.assertIsNone(invitation.revoked_at)
        self.assertIsNone(invitation.redeemed_at)
        self.assertFalse(HouseholdAccess.objects.exists())

    def _assert_tls_verification_failure(self, **settings):
        with tls_mailbox(**settings) as mailbox:
            with self.assertRaises(DeliveryFailure) as failure:
                self._invite()
            self._assert_sanitized_failure(failure.exception)
        self.assertEqual(mailbox.failed_handshakes, 1)
        self.assertEqual(len(mailbox.deliveries), 0)
        self._assert_invitation_revoked()

    def test_smtp_rejects_trusted_certificate_for_another_hostname(self):
        self._assert_tls_verification_failure(certificate_hostname="wrong-host.example.invalid")

    def test_smtp_rejects_untrusted_certificate_for_the_configured_hostname(self):
        self._assert_tls_verification_failure(trust_certificate=False)
