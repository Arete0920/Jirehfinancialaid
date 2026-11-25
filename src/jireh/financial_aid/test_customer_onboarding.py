"""First-household acceptance using real invitation and mailbox proof services."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from jireh.financial_aid.models import AidApplication
from jireh.runtime.customer_family_sessions import FAMILY_SESSION_KEY
from jireh.runtime.customer_onboarding import ONBOARDING_SESSION_KEY, _redeem_first_household
from jireh.schools.attempt_budget import MAX_REDEMPTION_ATTEMPTS
from jireh.schools.invitations import issue_household_invitation, revoke_household_invitation
from jireh.schools.models import (
    AcademicYear, Household, HouseholdAccess, HouseholdInvitation, MailboxChallenge,
    School, SchoolInvitationEvent, SchoolStaffAccess,
)
from jireh.schools.redemption import issue_mailbox_challenge

PASSWORD = "Fictional-Onboarding-Password-01234!"


@override_settings(
    ROOT_URLCONF="jireh.runtime.customer_urls", JIREH_CUSTOMER_CORE_ACCEPTANCE=True,
    JIREH_CUSTOMER_FAMILY_SESSION_ACCEPTANCE=True, JIREH_CUSTOMER_ONBOARDING_ACCEPTANCE=True,
    DEBUG=False, SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True,
    CSRF_COOKIE_SECURE=True, CSRF_COOKIE_HTTPONLY=True, SECURE_SSL_REDIRECT=True,
    SESSION_ENGINE="django.contrib.sessions.backends.db",
    JIREH_CUSTOMER_WORKSPACE_ACCEPTANCE=False, JIREH_SYNTHETIC_SUBMISSION_ONLY=False,
    JIREH_SYNTHETIC_DOCUMENTS_ONLY=False, JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE=False,
    JIREH_SYNTHETIC_APPLICATION_REVIEW=False, JIREH_OPERATOR_CREDENTIAL_RECOVERY_ENABLED=False,
)
class CustomerOnboardingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.parent = users.create_user(username="new-parent", password=PASSWORD)
        cls.other = users.create_user(username="other-parent", password=PASSWORD)
        cls.director = users.create_user(username="school-director", password=PASSWORD)
        cls.school = School.objects.create(code="onboarding-a", name="Fictional A")
        cls.other_school = School.objects.create(code="onboarding-b", name="Fictional B")
        cls.year = AcademicYear.objects.create(school=cls.school, name="2026-27",
                                               start_date=date(2026, 8, 1), end_date=date(2027, 6, 30))
        cls.household = Household.objects.create(school=cls.school, name="New family")
        cls.other_household = Household.objects.create(school=cls.other_school, name="Other family")
        SchoolStaffAccess.objects.create(school=cls.school, user=cls.director,
                                         role=SchoolStaffAccess.ROLE_AID_DIRECTOR)

    def login(self, client, user, *, onboarding=True):
        name = "jireh_customer_onboarding_login" if onboarding else "jireh_customer_family_login"
        url = reverse(name)
        token = client.get(url, secure=True).json()["csrf_token"]
        return self.post(client, url, {"username": user.username, "password": PASSWORD}, token)

    def post(self, client, url, payload, token, *, origin="https://testserver"):
        return client.post(url, json.dumps(payload), content_type="application/json",
                           secure=True, HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN=origin)

    def token(self, client):
        return client.get(reverse("jireh_customer_onboarding_login"), secure=True).json()["csrf_token"]

    def redeem_url(self, school=None, household=None):
        return reverse("jireh_customer_onboarding_redeem", args=((school or self.school).pk,
                                                                 (household or self.household).pk))

    def invite(self, user=None):
        invitation, invite = issue_household_invitation(actor=self.director, school_id=self.school.pk,
                                                       household_id=self.household.pk, email="family@example.invalid")
        proof, mailbox = issue_mailbox_challenge(user=user or self.parent, email=invitation.email)
        return invitation, proof, {"invitation_token": invite, "mailbox_token": mailbox}

    def test_dual_proof_grant_requires_new_family_session(self):
        invitation, proof, payload = self.invite()
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.login(client, self.parent, onboarding=False).status_code, 401)
        self.assertEqual(self.login(client, self.parent).json(), {"authenticated": True, "invitation_only": True})
        self.assertTrue(client.session[ONBOARDING_SESSION_KEY])
        self.assertNotIn(FAMILY_SESSION_KEY, client.session)
        key = client.session.session_key
        draft = reverse("jireh_customer_draft", args=(self.school.pk, self.household.pk, self.year.pk))
        self.assertEqual(client.get(draft, secure=True).status_code, 403)
        self.assertEqual(self.post(client, draft, {}, self.token(client)).status_code, 403)
        self.assertEqual(AidApplication.objects.count(), 0)
        response = self.post(client, self.redeem_url(), payload, self.token(client))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "redeemed", "reauthentication_required": True})
        self.assertIn("no-store", response["Cache-Control"])
        for secret in payload.values():
            self.assertNotIn(secret, response.content.decode())
        invitation.refresh_from_db()
        proof.refresh_from_db()
        self.assertIsNotNone(invitation.redeemed_at)
        self.assertIsNotNone(proof.consumed_at)
        self.assertEqual(invitation.audit_events.filter(action="REDEEMED").count(), 1)
        self.assertEqual(HouseholdAccess.objects.filter(user=self.parent, household=self.household).count(), 1)
        self.assertFalse(Session.objects.filter(session_key=key).exists())
        self.assertEqual(client.get(draft, secure=True).status_code, 403)
        self.assertEqual(self.login(client, self.parent, onboarding=False).status_code, 200)
        self.assertTrue(client.session[FAMILY_SESSION_KEY])
        self.assertNotIn(ONBOARDING_SESSION_KEY, client.session)
        csrf = client.get(reverse("jireh_customer_csrf"), secure=True).json()["csrf_token"]
        self.assertEqual(client.post(draft, secure=True, HTTP_ORIGIN="https://testserver",
                                     HTTP_X_CSRFTOKEN=csrf).status_code, 200)
        self.assertEqual(AidApplication.objects.count(), 1)
        self.assertEqual(self.post(client, self.redeem_url(), payload, self.token(client)).status_code, 403)
        self.assertEqual(HouseholdAccess.objects.count(), 1)

    def test_wrong_scope_wrong_account_csrf_and_revoke_leave_no_grant(self):
        invitation, proof, payload = self.invite()
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.login(client, self.other).status_code, 200)
        self.assertEqual(self.post(client, self.redeem_url(), payload, self.token(client)).status_code, 404)
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.login(client, self.parent).status_code, 200)
        token = self.token(client)
        self.assertEqual(self.post(client, self.redeem_url(self.other_school, self.other_household), payload, token).status_code, 404)
        self.assertEqual(self.post(client, self.redeem_url(), payload, token, origin="https://untrusted.example").status_code, 403)
        revoke_household_invitation(actor=self.director, school_id=self.school.pk, invitation_id=invitation.pk)
        self.assertEqual(self.post(client, self.redeem_url(), payload, token).status_code, 404)
        invitation.refresh_from_db()
        proof.refresh_from_db()
        self.assertIsNone(invitation.redeemed_at)
        self.assertIsNone(proof.consumed_at)
        self.assertFalse(HouseholdAccess.objects.exists())

    def test_pending_session_cannot_gain_family_or_director_routes(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.login(client, self.parent).status_code, 200)
        url = reverse("jireh_customer_household", args=(self.school.pk, self.household.pk))
        HouseholdAccess.objects.create(household=self.household, user=self.parent)
        self.assertEqual(client.get(url, secure=True).status_code, 403)
        SchoolStaffAccess.objects.create(school=self.school, user=self.parent, role=SchoolStaffAccess.ROLE_AID_DIRECTOR)
        cases = reverse("jireh_customer_cases", args=(self.school.pk, self.year.pk))
        self.assertEqual(client.get(cases, secure=True).status_code, 403)
        self.assertEqual(self.post(client, self.redeem_url(), {}, self.token(client)).status_code, 403)
        token = self.token(client)
        logout = reverse("jireh_customer_onboarding_logout")
        key = client.session.session_key
        self.assertEqual(client.post(logout, secure=True, HTTP_ORIGIN="https://testserver", HTTP_X_CSRFTOKEN=token).status_code, 200)
        self.assertFalse(Session.objects.filter(session_key=key).exists())

    def test_disabled_flags_existing_grants_privileged_account_and_throttle(self):
        client = Client(enforce_csrf_checks=True)
        login_url = reverse("jireh_customer_onboarding_login")
        for flag in ("JIREH_CUSTOMER_ONBOARDING_ACCEPTANCE", "JIREH_CUSTOMER_FAMILY_SESSION_ACCEPTANCE", "JIREH_CUSTOMER_CORE_ACCEPTANCE"):
            with self.subTest(flag=flag), self.settings(**{flag: False}):
                self.assertEqual(client.get(login_url, secure=True).status_code, 404)
        with self.settings(ROOT_URLCONF="jireh.runtime.urls"):
            self.assertEqual(client.get(login_url, secure=True).status_code, 404)
        self.assertEqual(client.get(login_url).status_code, 404)
        self.assertEqual(self.login(client, self.director).status_code, 401)
        HouseholdAccess.objects.create(household=self.household, user=self.other, is_active=False)
        self.assertEqual(self.login(client, self.other).status_code, 401)
        self.assertEqual(self.login(client, self.parent).status_code, 200)
        token = self.token(client)
        with patch("jireh.schools.redemption_views.charge_redemption_attempt", side_effect=DatabaseError("secret details")):
            response = self.post(client, self.redeem_url(), {}, token)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret", response.content.decode())
        for _ in range(MAX_REDEMPTION_ATTEMPTS):
            self.assertEqual(self.post(client, self.redeem_url(), {}, token).status_code, 400)
        response = self.post(client, self.redeem_url(), {}, token)
        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response["Retry-After"]), 0)
        self.assertFalse(HouseholdAccess.objects.filter(user=self.parent).exists())


@skipUnless(connection.vendor == "postgresql", "PostgreSQL row locking required")
class FirstHouseholdConcurrencyTests(TransactionTestCase):
    def test_two_valid_invitations_for_one_account_create_only_one_first_grant(self):
        user = get_user_model().objects.create_user(username="concurrent-family")
        scopes = []
        for index in (1, 2):
            school = School.objects.create(code=f"first-grant-{index}", name=f"Fictional {index}")
            household = Household.objects.create(school=school, name="Fictional household")
            director = get_user_model().objects.create_user(username=f"concurrent-director-{index}")
            SchoolStaffAccess.objects.create(school=school, user=director, role=SchoolStaffAccess.ROLE_AID_DIRECTOR)
            email = f"family-{index}@example.invalid"
            _, invite = issue_household_invitation(actor=director, school_id=school.pk,
                                                   household_id=household.pk, email=email)
            _, mailbox = issue_mailbox_challenge(user=user, email=email)
            scopes.append(dict(school_id=school.pk, household_id=household.pk,
                               invitation_token=invite, mailbox_token=mailbox))
        barrier = Barrier(2)

        def redeem(scope):
            close_old_connections()
            try:
                account = get_user_model().objects.get(pk=user.pk)
                barrier.wait(timeout=10)
                try:
                    _redeem_first_household(user=account, **scope)
                    return "redeemed"
                except PermissionDenied:
                    return "denied"
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(redeem, scope) for scope in scopes]
            outcomes = [future.result(timeout=30) for future in futures]
        self.assertCountEqual(outcomes, ["redeemed", "denied"])
        self.assertEqual(HouseholdAccess.objects.filter(user=user).count(), 1)
        self.assertEqual(HouseholdInvitation.objects.filter(redeemed_by=user).count(), 1)
        self.assertEqual(MailboxChallenge.objects.filter(user=user, consumed_at__isnull=False).count(), 1)
        self.assertEqual(SchoolInvitationEvent.objects.filter(actor_user=user, action="REDEEMED").count(), 1)
