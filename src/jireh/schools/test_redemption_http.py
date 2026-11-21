"""CSRF-protected redemption HTTP tests, using disposable Django test routes."""

import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .invitations import issue_household_invitation, revoke_household_invitation
from .models import (
    Household, HouseholdAccess, HouseholdInvitation, MailboxChallenge,
    School, SchoolInvitationEvent, SchoolStaffAccess,
)
from .redemption import issue_mailbox_challenge


class RedemptionHTTPTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.director = User.objects.create_user(
            username="redeem-http-director", password="test-password"
        )
        cls.parent = User.objects.create_user(
            username="redeem-http-family", password="test-password"
        )
        cls.other_parent = User.objects.create_user(
            username="redeem-http-other-family", password="test-password"
        )
        cls.school = School.objects.create(code="redeem-http-a", name="School A")
        cls.other_school = School.objects.create(
            code="redeem-http-b", name="School B"
        )
        cls.household = Household.objects.create(
            school=cls.school, name="Household A"
        )
        cls.other_household = Household.objects.create(
            school=cls.other_school, name="Household B"
        )
        SchoolStaffAccess.objects.create(
            school=cls.school,
            user=cls.director,
            role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        )

    def url(self, school=None, household=None):
        return reverse(
            "jireh_test_household_redemption",
            kwargs={
                "school_id": (school or self.school).pk,
                "household_id": (household or self.household).pk,
            },
        )

    def credentials(self):
        invitation, invitation_code = issue_household_invitation(
            actor=self.director, school_id=self.school.pk,
            household_id=self.household.pk, email="family@example.org",
        )
        challenge, mailbox_code = issue_mailbox_challenge(
            user=self.parent, email="family@example.org",
        )
        return invitation, challenge, {
            "invitation_token": invitation_code,
            "mailbox_token": mailbox_code,
        }

    def client_with_csrf(self, user=None, url=None):
        client = Client(enforce_csrf_checks=True)
        client.force_login(user or self.parent)
        response = client.get(url or self.url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ready": True})
        self.assertIn("csrftoken", client.cookies)
        return client, client.cookies["csrftoken"].value

    def post(self, client, payload, *, url=None, csrf=None, content_type="application/json"):
        kwargs = {"content_type": content_type}
        if csrf is not None:
            kwargs["HTTP_X_CSRFTOKEN"] = csrf
        return client.post(
            url or self.url(),
            data=(json.dumps(payload) if not isinstance(payload, str) else payload),
            **kwargs,
        )

    def test_get_does_not_grant_access_and_requires_login(self):
        client = Client(enforce_csrf_checks=True)
        anonymous = client.get(self.url())
        self.assertEqual(anonymous.status_code, 403)
        self.assertEqual(anonymous.json(), {"detail": "Forbidden."})
        self.assertEqual(HouseholdAccess.objects.count(), 0)
        logged_in, _ = self.client_with_csrf()
        self.assertIn("no-store", logged_in.get(self.url())["Cache-Control"])
        self.assertEqual(HouseholdAccess.objects.count(), 0)

    def test_post_requires_csrf_even_with_authenticated_session(self):
        _, _, codes = self.credentials()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.parent)
        r = self.post(client, codes)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(HouseholdAccess.objects.count(), 0)

    def test_post_consumes_two_codes_once_and_hides_secrets(self):
        invitation, proof, codes = self.credentials()
        client, csrf = self.client_with_csrf()
        response = self.post(client, codes, csrf=csrf)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"household_id": str(self.household.pk), "status": "redeemed"},
        )
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn(codes["invitation_token"], response.content.decode())
        self.assertNotIn(codes["mailbox_token"], response.content.decode())
        self.assertEqual(HouseholdAccess.objects.count(), 1)
        self.assertEqual(
            SchoolInvitationEvent.objects.filter(action="REDEEMED").count(), 1
        )
        invitation.refresh_from_db()
        proof.refresh_from_db()
        self.assertIsNotNone(invitation.redeemed_at)
        self.assertIsNotNone(proof.consumed_at)
        replay = self.post(client, codes, csrf=csrf)
        self.assertEqual(replay.status_code, 404)
        self.assertEqual(replay.json(), {"detail": "Not found."})
        self.assertEqual(HouseholdAccess.objects.count(), 1)

    def test_wrong_account_and_wrong_scope_denied(self):
        _, _, codes = self.credentials()
        other, other_csrf = self.client_with_csrf(user=self.other_parent)
        self.assertEqual(self.post(other, codes, csrf=other_csrf).status_code, 404)
        client, csrf = self.client_with_csrf()
        for url in (
            self.url(school=self.other_school),
            self.url(household=self.other_household),
            self.url(school=self.other_school, household=self.other_household),
        ):
            with self.subTest(url=url):
                self.assertEqual(
                    self.post(client, codes, url=url, csrf=csrf).status_code,
                    404,
                )
        self.assertEqual(HouseholdAccess.objects.count(), 0)

    def test_revoked_invitation_denied(self):
        invitation, _, codes = self.credentials()
        revoke_household_invitation(
            actor=self.director,
            school_id=self.school.pk,
            invitation_id=invitation.pk,
        )
        client, csrf = self.client_with_csrf()
        self.assertEqual(self.post(client, codes, csrf=csrf).status_code, 404)
        self.assertEqual(HouseholdAccess.objects.count(), 0)

    def test_anonymous_post_denied(self):
        _, _, codes = self.credentials()
        client = Client(enforce_csrf_checks=False)
        response = self.post(client, codes)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(HouseholdAccess.objects.count(), 0)

    def test_strict_json_rejects_duplicate_keys_non_json_and_large_bodies(self):
        _, _, codes = self.credentials()
        client, csrf = self.client_with_csrf()
        invalid = (
            '{"invitation_token":"x","invitation_token":"y","mailbox_token":"z"}',
            '{"invitation_token":"x"}',
            '{"invitation_token":null,"mailbox_token":"y"}',
            '[]',
            '{broken',
            '{}',
            'a' * 513,
        )
        for body in invalid:
            with self.subTest(body=body[:20]):
                response = self.post(client, body, csrf=csrf)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json(), {"detail": "Invalid request."})
        wrong_type = self.post(
            client, codes, csrf=csrf, content_type="text/plain",
        )
        self.assertEqual(wrong_type.status_code, 400)
        self.assertEqual(HouseholdAccess.objects.count(), 0)

    def test_invalid_token_and_extra_fields_denied_without_grant(self):
        _, _, codes = self.credentials()
        client, csrf = self.client_with_csrf()
        for payload in (
            {**codes, "extra": "x"},
            {**codes, "invitation_token": "a" * 64},
            {**codes, "mailbox_token": "b" * 64},
        ):
            with self.subTest(case=tuple(payload)):
                response = self.post(client, payload, csrf=csrf)
                self.assertIn(response.status_code, (400, 404))
        self.assertEqual(HouseholdAccess.objects.count(), 0)

    def test_get_and_post_reject_inactive_user(self):
        _, _, codes = self.credentials()
        client, csrf = self.client_with_csrf()
        self.parent.is_active = False
        self.parent.save()
        self.assertEqual(client.get(self.url()).status_code, 403)
        self.assertEqual(self.post(client, codes, csrf=csrf).status_code, 403)
        self.assertEqual(HouseholdAccess.objects.count(), 0)

    def test_unsupported_methods_are_not_allowed(self):
        client, csrf = self.client_with_csrf()
        for call in (client.put, client.patch, client.delete):
            with self.subTest(method=call.__name__):
                self.assertEqual(
                    call(self.url(), HTTP_X_CSRFTOKEN=csrf).status_code, 405
                )
        self.assertEqual(HouseholdAccess.objects.count(), 0)
