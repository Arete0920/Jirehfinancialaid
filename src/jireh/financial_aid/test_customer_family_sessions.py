"""Disposable acceptance for family-only password sessions and role separation."""
import json
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.db import DatabaseError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from jireh.runtime.customer_family_sessions import FAMILY_SESSION_KEY
from jireh.schools.login_budget import MAX_LOGIN_ATTEMPTS
from jireh.schools.models import AcademicYear, Household, HouseholdAccess, School, SchoolStaffAccess


PASSWORD = "Synthetic-Test-Family-Password-01234!"


@override_settings(
    ROOT_URLCONF="jireh.runtime.customer_urls", JIREH_CUSTOMER_CORE_ACCEPTANCE=True,
    JIREH_CUSTOMER_FAMILY_SESSION_ACCEPTANCE=True,
    DEBUG=False, SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True,
    CSRF_COOKIE_SECURE=True, CSRF_COOKIE_HTTPONLY=True, SECURE_SSL_REDIRECT=True,
    SESSION_ENGINE="django.contrib.sessions.backends.db",
    JIREH_CUSTOMER_WORKSPACE_ACCEPTANCE=False, JIREH_SYNTHETIC_SUBMISSION_ONLY=False,
    JIREH_SYNTHETIC_DOCUMENTS_ONLY=False, JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE=False,
    JIREH_SYNTHETIC_APPLICATION_REVIEW=False, JIREH_OPERATOR_CREDENTIAL_RECOVERY_ENABLED=False,
)
class CustomerFamilySessionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user = get_user_model()
        cls.parent = user.objects.create_user(username="session-parent", password=PASSWORD)
        cls.ungranted = user.objects.create_user(username="session-ungranted", password=PASSWORD)
        cls.director = user.objects.create_user(username="session-director", password=PASSWORD)
        cls.mixed = user.objects.create_user(username="session-mixed", password=PASSWORD)
        cls.admin = user.objects.create_superuser(username="session-admin", password=PASSWORD)
        cls.school = School.objects.create(code="family-session-school", name="Fictional school")
        cls.year = AcademicYear.objects.create(school=cls.school, name="2026-27",
                                               start_date=date(2026, 8, 1), end_date=date(2027, 6, 30))
        cls.household = Household.objects.create(school=cls.school, name="Fictional household")
        for account in (cls.parent, cls.mixed, cls.admin):
            HouseholdAccess.objects.create(household=cls.household, user=account)
        for account in (cls.director, cls.mixed):
            SchoolStaffAccess.objects.create(school=cls.school, user=account,
                                             role=SchoolStaffAccess.ROLE_AID_DIRECTOR)

    def sign_in(self, client, username, password=PASSWORD):
        url = reverse("jireh_customer_family_login")
        token = client.get(url, secure=True).json()["csrf_token"]
        return client.post(url, json.dumps({"username": username, "password": password}),
                           content_type="application/json", secure=True,
                           HTTP_ORIGIN="https://testserver", HTTP_X_CSRFTOKEN=token)

    def household_url(self):
        return reverse("jireh_customer_household", args=(self.school.pk, self.household.pk))

    def test_password_session_rotates_key_and_logout_invalidates(self):
        client = Client(enforce_csrf_checks=True)
        anonymous = client.session
        anonymous["marker"] = "fixture"
        anonymous.save()
        old_key = anonymous.session_key
        response = self.sign_in(client, self.parent.username)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"authenticated": True})
        self.assertTrue(client.session[FAMILY_SESSION_KEY])
        self.assertNotEqual(old_key, client.session.session_key)
        self.assertFalse(Session.objects.filter(session_key=old_key).exists())
        self.assertLessEqual(client.session.get_expiry_age(), 900)
        self.assertTrue(client.cookies["sessionid"]["secure"])
        self.assertTrue(client.cookies["sessionid"]["httponly"])
        self.assertEqual(client.get(self.household_url(), secure=True).status_code, 200)
        self.assertEqual(self.sign_in(client, self.ungranted.username).status_code, 403)
        token = client.get(reverse("jireh_customer_csrf"), secure=True).json()["csrf_token"]
        logout_url = reverse("jireh_customer_family_logout")
        self.assertEqual(client.post(logout_url, secure=True).status_code, 403)
        key = client.session.session_key
        self.assertEqual(client.post(logout_url, secure=True, HTTP_ORIGIN="https://testserver",
                                     HTTP_X_CSRFTOKEN=token).status_code, 200)
        self.assertFalse(Session.objects.filter(session_key=key).exists())
        self.assertEqual(client.get(self.household_url(), secure=True).status_code, 403)

    def test_pre_auth_csrf_and_secure_route_flags(self):
        client = Client(enforce_csrf_checks=True)
        url = reverse("jireh_customer_family_login")
        response = client.get(url, secure=True)
        token = response.json()["csrf_token"]
        self.assertIn("no-store", response["Cache-Control"])
        self.assertTrue(client.cookies["csrftoken"]["httponly"])
        self.assertNotEqual(token, client.cookies["csrftoken"].value)
        payload = json.dumps({"username": self.parent.username, "password": PASSWORD})
        self.assertEqual(client.post(url, payload, content_type="application/json", secure=True).status_code, 403)
        self.assertEqual(client.post(url, payload, content_type="application/json", secure=True,
                                     HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN="https://evil.example").status_code, 403)
        self.assertEqual(client.get(url).status_code, 404)
        for flag, value in (("JIREH_CUSTOMER_FAMILY_SESSION_ACCEPTANCE", False),
                            ("JIREH_CUSTOMER_CORE_ACCEPTANCE", False),
                            ("CSRF_COOKIE_HTTPONLY", False), ("JIREH_SYNTHETIC_SUBMISSION_ONLY", True)):
            with self.subTest(flag=flag), self.settings(**{flag: value}):
                self.assertEqual(client.get(url, secure=True).status_code, 404)
        with self.settings(ROOT_URLCONF="jireh.runtime.urls"):
            self.assertEqual(client.get(url, secure=True).status_code, 404)

    def test_ungranted_privileged_and_invalid_credentials_are_indistinguishable(self):
        for username, password in ((self.ungranted.username, PASSWORD), (self.director.username, PASSWORD),
                                   (self.mixed.username, PASSWORD), (self.admin.username, PASSWORD),
                                   ("unknown-account", PASSWORD), (self.parent.username, "wrong")):
            with self.subTest(username=username):
                client = Client(enforce_csrf_checks=True)
                response = self.sign_in(client, username, password)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json(), {"detail": "Invalid credentials."})
                self.assertNotIn(FAMILY_SESSION_KEY, client.session)

    def test_role_change_and_revocation_cannot_elevate_family_session(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.sign_in(client, self.parent.username).status_code, 200)
        token = client.get(reverse("jireh_customer_csrf"), secure=True).json()["csrf_token"]
        director = reverse("jireh_customer_cases", args=(self.school.pk, self.year.pk))
        self.assertEqual(client.get(director, secure=True).status_code, 403)
        SchoolStaffAccess.objects.create(school=self.school, user=self.parent,
                                         role=SchoolStaffAccess.ROLE_AID_DIRECTOR)
        self.assertEqual(client.get(director, secure=True).status_code, 403)
        self.assertEqual(client.get(self.household_url(), secure=True).status_code, 403)
        SchoolStaffAccess.objects.filter(user=self.parent).update(is_active=False)
        self.assertEqual(client.get(self.household_url(), secure=True).status_code, 200)
        with self.settings(JIREH_CUSTOMER_FAMILY_SESSION_ACCEPTANCE=False):
            self.assertEqual(client.get(self.household_url(), secure=True).status_code, 403)
        HouseholdAccess.objects.filter(user=self.parent).update(is_active=False)
        self.assertEqual(client.get(self.household_url(), secure=True).status_code, 403)
        self.assertEqual(client.post(reverse("jireh_customer_family_logout"), secure=True,
                                     HTTP_ORIGIN="https://testserver", HTTP_X_CSRFTOKEN=token).status_code, 200)

    def test_attempt_budget_and_database_failure_fail_closed(self):
        for _ in range(MAX_LOGIN_ATTEMPTS):
            self.assertEqual(self.sign_in(Client(enforce_csrf_checks=True), self.parent.username,
                                          "wrong").status_code, 401)
        response = self.sign_in(Client(enforce_csrf_checks=True), self.parent.username)
        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response["Retry-After"]), 0)
        with patch("jireh.schools.session_views.charge_login_attempt", side_effect=DatabaseError("private")):
            response = self.sign_in(Client(enforce_csrf_checks=True), self.ungranted.username)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private", response.content.decode())
