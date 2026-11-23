"""Rehearse fictional household onboarding with Django's local memory mailbox."""

import re
from unittest.mock import patch

from django.contrib.auth import SESSION_KEY
from django.core import mail
from django.core.mail.backends.locmem import EmailBackend
from django.http import Http404
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse

from .delivery import deliver_household_invitation, deliver_mailbox_challenge
from .demo_seed import DEMO_PASSWORD, seed_synthetic_browser_demo
from .grant_admin import revoke_household_access
from .models import (
    HouseholdAccess, HouseholdInvitation, MailboxChallenge,
    SchoolGrantDecisionEvent, SchoolInvitationEvent,
)


_RECIPIENT = "fictional-family@example.invalid"
_SENDER = "fictional-school@example.invalid"
_MAIL_CODE = re.compile(r"\n\n([A-Za-z0-9_-]{64})\n\n")


_MAIL_SETTINGS = dict(
    JIREH_EMAIL_DELIVERY_ENABLED=True,
    EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
    EMAIL_HOST="onboarding-mail.example.invalid",
    EMAIL_PORT=587,
    EMAIL_USE_TLS=True,
    EMAIL_USE_SSL=False,
    EMAIL_HOST_USER="fictional-mail-user",
    EMAIL_HOST_PASSWORD="fictional-mail-password",
    EMAIL_TIMEOUT=5,
    JIREH_EMAIL_FROM=_SENDER,
)


class FictionalOnboardingRehearsal:
    def _mailbox_code(self, message, subject):
        self.assertEqual(message.from_email, _SENDER)
        self.assertEqual(message.recipients(), [_RECIPIENT])
        self.assertTrue(message.subject == subject, "Unexpected mailbox subject.")
        match = _MAIL_CODE.search(message.body)
        self.assertIsNotNone(match, "Expected a code in the fictional mailbox message.")
        return match.group(1)

    def _assert_invitation_denied(self, *, actor, school_id, household_id):
        with self.assertRaises(Http404):
            deliver_household_invitation(
                actor=actor, school_id=school_id, household_id=household_id,
                email=_RECIPIENT,
            )
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(HouseholdInvitation.objects.exists())

    @override_settings(**_MAIL_SETTINGS)
    def assert_fictional_invitation_denied(self, demo, *, actor):
        with patch("django.core.mail.backends.smtp.EmailBackend", EmailBackend):
            self._assert_invitation_denied(
                actor=actor, school_id=demo["school_a"].pk,
                household_id=demo["household_a"].pk,
            )

    @override_settings(**_MAIL_SETTINGS)
    def rehearse_household_onboarding(self, demo):
        director = demo["director_a"]
        family = demo["parent"]
        scope = {
            "school_id": demo["school_a"].pk, "household_id": demo["household_a"].pk,
        }
        other_scope = {
            "school_id": demo["school_b"].pk, "household_id": demo["household_b"].pk,
        }
        household_url = reverse("jireh_household_detail", kwargs=scope)
        other_household_url = reverse("jireh_household_detail", kwargs=other_scope)
        redeem_url = reverse("jireh_test_household_redemption", kwargs=scope)
        client = Client(enforce_csrf_checks=True)
        self.addCleanup(mail.outbox.clear)

        self.assertFalse(HouseholdAccess.objects.exists())
        self.assertEqual(client.get(household_url).status_code, 403)

        # Keep Jireh's service policy and message construction in the path.
        # Substitute Django's transport so no SMTP socket or real mailbox is used.
        with patch("django.core.mail.backends.smtp.EmailBackend", EmailBackend):
            self._assert_invitation_denied(actor=demo["director_b"], **scope)

            invitation_id = deliver_household_invitation(
                actor=director, email=_RECIPIENT, **scope,
            )
            self.assertEqual(len(mail.outbox), 1)
            invitation_code = self._mailbox_code(mail.outbox[0], "Jireh Financial Aid invitation")

            login_url = reverse("jireh_test_family_login")
            self.assertEqual(client.get(login_url).status_code, 200)
            signed_in = client.post(
                login_url, {"username": family.username, "password": DEMO_PASSWORD},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
            )
            self.assertEqual(signed_in.status_code, 200)
            self.assertEqual(signed_in.json(), {"authenticated": True})
            self.assertEqual(client.get(household_url).status_code, 404)
            self.assertFalse(HouseholdAccess.objects.exists())

            challenge_id = deliver_mailbox_challenge(
                user=signed_in.wsgi_request.user, invitation_token=invitation_code, **scope,
            )
            self.assertEqual(len(mail.outbox), 2)
            mailbox_code = self._mailbox_code(mail.outbox[1], "Jireh Financial Aid email verification")

        self.assertTrue(invitation_code != mailbox_code, "The two messages must carry separate codes.")
        self.assertEqual(client.get(redeem_url).status_code, 200)
        payload = {"invitation_token": invitation_code, "mailbox_token": mailbox_code}
        headers = {
            "content_type": "application/json",
            "HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value,
        }
        other_redeem = reverse("jireh_test_household_redemption", kwargs=other_scope)
        self.assertEqual(
            client.post(redeem_url, payload, content_type="application/json").status_code, 403,
        )
        self.assertEqual(client.post(other_redeem, payload, **headers).status_code, 404)
        self.assertFalse(HouseholdAccess.objects.exists())
        redeemed = client.post(redeem_url, payload, **headers)
        self.assertEqual(redeemed.status_code, 200)
        self.assertEqual(
            redeemed.json(), {"household_id": str(scope["household_id"]), "status": "redeemed"},
        )
        self.assertEqual(client.post(redeem_url, payload, **headers).status_code, 404)

        invitation = HouseholdInvitation.objects.get(pk=invitation_id)
        challenge = MailboxChallenge.objects.get(pk=challenge_id)
        self.assertIsNotNone(invitation.redeemed_at)
        self.assertIsNotNone(challenge.consumed_at)
        self.assertEqual(challenge.user_id, family.pk)
        self.assertCountEqual(
            SchoolInvitationEvent.objects.filter(invitation=invitation).values_list(
                "action", "actor_user_id",
            ),
            [
                (SchoolInvitationEvent.ACTION_ISSUED, director.pk),
                (SchoolInvitationEvent.ACTION_REDEEMED, family.pk),
            ],
        )
        self.assertEqual(HouseholdAccess.objects.count(), 1)
        session_key = client.session.session_key
        self.assertTrue(session_key, "Expected an authenticated session before revocation.")
        household = client.get(household_url)
        self.assertEqual(household.status_code, 200)
        self.assertEqual(household.json()["id"], str(scope["household_id"]))
        self.assertEqual(client.get(other_household_url).status_code, 404)

        with self.assertRaises(Http404):
            revoke_household_access(actor=demo["director_b"], subject_user_id=family.pk, **scope)
        self.assertEqual(client.get(household_url).status_code, 200)
        grant = revoke_household_access(actor=director, subject_user_id=family.pk, **scope)
        self.assertFalse(grant.is_active)
        self.assertEqual(client.get(household_url).status_code, 404)
        self.assertTrue(client.session.session_key == session_key, "The same session must be checked.")
        self.assertEqual(client.session[SESSION_KEY], str(family.pk))
        event = SchoolGrantDecisionEvent.objects.get(
            grant_id=grant.pk, action=SchoolGrantDecisionEvent.ACTION_REVOKED,
        )
        self.assertEqual(event.actor_user_id, director.pk)
        self.assertEqual(event.school_id, scope["school_id"])
        self.assertEqual(event.target_user_id, family.pk)


class FictionalOnboardingRehearsalTests(FictionalOnboardingRehearsal, TransactionTestCase):
    def test_director_invitation_through_revocation_of_a_signed_in_family(self):
        self.rehearse_household_onboarding(
            seed_synthetic_browser_demo(grant_family_access=False)
        )
