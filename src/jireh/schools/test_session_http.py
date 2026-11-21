"""Test-only family login/logout with session security and credential throttling."""

import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .login_budget import (
    LOGIN_ATTEMPT_WINDOW,
    MAX_LOGIN_ATTEMPTS,
    charge_login_attempt,
)
from .models import Household, HouseholdAccess, LoginAttemptBudget, School
from .session_views import LOGIN_SESSION_LIFETIME_SECONDS


PASSWORD = "Synthetic-Test-Password-01234!"


class TestOnlyFamilySessionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.parent = User.objects.create_user(
            username="family-login-parent", password=PASSWORD,
        )
        cls.other_parent = User.objects.create_user(
            username="family-login-other", password=PASSWORD,
        )
        cls.inactive = User.objects.create_user(
            username="family-login-inactive",
            password=PASSWORD, is_active=False,
        )
        cls.school = School.objects.create(
            code="session-test-school", name="Session Test School",
        )
        cls.household = Household.objects.create(
            school=cls.school, name="Session Test Household",
        )
        HouseholdAccess.objects.create(
            household=cls.household, user=cls.parent,
        )

    @staticmethod
    def login_url():
        return reverse("jireh_test_family_login")

    @staticmethod
    def logout_url():
        return reverse("jireh_test_family_logout")

    def household_url(self):
        return reverse(
            "jireh_household_detail",
            kwargs={
                "school_id": self.school.pk,
                "household_id": self.household.pk,
            },
        )

    def new_client(self):
        client = Client(enforce_csrf_checks=True)
        response = client.get(self.login_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ready": True})
        self.assertIn("csrftoken", client.cookies)
        self.assertIn("no-store", response["Cache-Control"])
        return client, client.cookies["csrftoken"].value

    def login(self, client, csrf, *, username="family-login-parent", password=PASSWORD):
        return client.post(
            self.login_url(),
            data=json.dumps({"username": username, "password": password}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )

    def test_login_rotates_session_key_and_uses_short_expiry(self):
        client, csrf = self.new_client()
        anonymous = client.session
        anonymous["test_nonsecret_marker"] = "present"
        anonymous.save()
        old_key = anonymous.session_key
        self.assertIsNotNone(old_key)

        result = self.login(client, csrf)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {"authenticated": True})
        self.assertNotIn(PASSWORD, result.content.decode())
        self.assertIn("no-store", result["Cache-Control"])
        new_key = client.session.session_key
        self.assertNotEqual(new_key, old_key)
        self.assertEqual(
            client.session.get("_auth_user_id"), str(self.parent.pk),
        )
        self.assertGreater(client.session.get_expiry_age(), 0)
        self.assertLessEqual(
            client.session.get_expiry_age(),
            LOGIN_SESSION_LIFETIME_SECONDS,
        )
        self.assertEqual(LOGIN_SESSION_LIFETIME_SECONDS, 900)
        self.assertTrue(client.cookies["sessionid"]["httponly"])
        self.assertEqual(client.get(self.household_url()).status_code, 200)

    def test_logout_requires_csrf_and_invalidates_authenticated_session(self):
        client, csrf = self.new_client()
        self.assertEqual(self.login(client, csrf).status_code, 200)
        self.assertEqual(client.get(self.household_url()).status_code, 200)
        logged_in_key = client.session.session_key

        missing_csrf = client.post(self.logout_url())
        self.assertEqual(missing_csrf.status_code, 403)
        self.assertEqual(client.get(self.household_url()).status_code, 200)

        current_csrf = client.cookies["csrftoken"].value
        result = client.post(
            self.logout_url(), HTTP_X_CSRFTOKEN=current_csrf
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {"authenticated": False})
        self.assertIn("no-store", result["Cache-Control"])
        self.assertNotEqual(client.session.session_key, logged_in_key)
        self.assertEqual(client.get(self.household_url()).status_code, 403)

    def test_login_requires_csrf_and_does_not_store_attempt(self):
        client, _ = self.new_client()
        response = client.post(
            self.login_url(),
            data=json.dumps({
                "username": "family-login-parent", "password": PASSWORD,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(LoginAttemptBudget.objects.exists())
        self.assertEqual(client.get(self.household_url()).status_code, 403)

    def test_unknown_and_wrong_password_have_identical_response(self):
        for username, password in (
            ("missing-user", PASSWORD),
            ("family-login-parent", "incorrect"),
            ("family-login-inactive", PASSWORD),
        ):
            client, csrf = self.new_client()
            response = self.login(
                client, csrf, username=username, password=password,
            )
            self.assertEqual(response.status_code, 401)
            self.assertEqual(
                response.json(), {"detail": "Invalid credentials."},
            )
            self.assertNotIn(username, response.content.decode())
            self.assertNotIn(password, response.content.decode())
            self.assertEqual(client.get(self.household_url()).status_code, 403)
        self.assertEqual(LoginAttemptBudget.objects.count(), 3)

    def test_login_attempts_are_shared_across_sessions_and_casefolded(self):
        first, token1 = self.new_client()
        second, token2 = self.new_client()
        for i in range(MAX_LOGIN_ATTEMPTS):
            client, csrf = (first, token1) if i % 2 == 0 else (second, token2)
            username = (
                "family-login-parent" if i % 2 == 0
                else "FAMILY-LOGIN-PARENT"
            )
            response = self.login(
                client, csrf, username=username, password="incorrect",
            )
            self.assertEqual(response.status_code, 401)

        self.assertEqual(LoginAttemptBudget.objects.count(), 1)
        budget = LoginAttemptBudget.objects.get()
        self.assertEqual(budget.attempt_count, 10)
        self.assertEqual(len(budget.identifier_digest), 64)
        self.assertNotIn("family-login-parent", budget.identifier_digest)

        denied = self.login(first, token1)
        self.assertEqual(denied.status_code, 429)
        self.assertEqual(
            denied.json(), {"detail": "Too many sign-in attempts."},
        )
        self.assertGreaterEqual(int(denied["Retry-After"]), 1)
        self.assertLessEqual(int(denied["Retry-After"]), 900)
        self.assertIn("no-store", denied["Cache-Control"])
        self.assertEqual(first.get(self.household_url()).status_code, 403)

    def test_unrelated_identifier_has_independent_budget(self):
        first, csrf = self.new_client()
        for _ in range(10):
            self.assertEqual(
                self.login(first, csrf, password="incorrect").status_code,
                401,
            )
        self.assertEqual(self.login(first, csrf).status_code, 429)

        other, other_csrf = self.new_client()
        response = self.login(
            other, other_csrf, username="family-login-other",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(LoginAttemptBudget.objects.count(), 2)

    def test_bounded_login_payload_and_duplicate_keys(self):
        client, csrf = self.new_client()
        for data in (
            '{"username":"x","username":"y","password":"secret"}',
            '{"username":"x"}',
            '{"username":null,"password":"secret"}',
            json.dumps({"username": "invalid" + chr(0) + "user", "password": PASSWORD}),
            json.dumps({"username": "  spaced", "password": PASSWORD}),
            json.dumps({"username": "x" * 151, "password": PASSWORD}),
            '{"username":"x","password":null}',
            '{"username":"x","password":"secret","extra":1}',
            '[]',
            '{}',
            '{broken',
            "x" * 2049,
        ):
            with self.subTest(payload=data[:20]):
                response = client.post(
                    self.login_url(), data=data,
                    content_type="application/json",
                    HTTP_X_CSRFTOKEN=csrf,
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.json(), {"detail": "Invalid request."},
                )
        wrong_type = client.post(
            self.login_url(),
            data="username=family-login-parent",
            content_type="text/plain",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(wrong_type.status_code, 400)
        self.assertFalse(LoginAttemptBudget.objects.exists())

    def test_throttle_database_outage_fails_closed_before_authentication(self):
        client, csrf = self.new_client()
        with patch(
            "jireh.schools.session_views.charge_login_attempt",
            side_effect=DatabaseError("sensitive database diagnostics"),
        ):
            with patch("jireh.schools.session_views.authenticate") as check:
                response = self.login(client, csrf)
                check.assert_not_called()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(), {"detail": "Service unavailable."},
        )
        self.assertNotIn("sensitive", response.content.decode())
        self.assertEqual(client.get(self.household_url()).status_code, 403)

    def test_get_logout_and_other_methods_do_not_create_sessions(self):
        client, csrf = self.new_client()
        self.assertEqual(client.get(self.logout_url()).status_code, 405)
        self.assertEqual(
            client.put(
                self.login_url(),
                HTTP_X_CSRFTOKEN=csrf,
            ).status_code,
            405,
        )
        self.assertEqual(
            client.delete(
                self.logout_url(),
                HTTP_X_CSRFTOKEN=csrf,
            ).status_code,
            405,
        )
        self.assertEqual(client.get(self.household_url()).status_code, 403)

    def test_already_authenticated_login_cannot_switch_identity(self):
        client, csrf = self.new_client()
        self.assertEqual(self.login(client, csrf).status_code, 200)
        csrf_after = client.cookies["csrftoken"].value
        denied = self.login(
            client, csrf_after, username="family-login-other",
        )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(client.session["_auth_user_id"], str(self.parent.pk))
        self.assertEqual(LoginAttemptBudget.objects.count(), 1)

    def test_budget_window_expiration_resets_one_record(self):
        now = timezone.now()
        with patch("jireh.schools.login_budget.timezone.now", return_value=now):
            for _ in range(MAX_LOGIN_ATTEMPTS):
                self.assertEqual(
                    charge_login_attempt(username="unknown-user"), (True, 0)
                )
            self.assertEqual(
                charge_login_attempt(username="unknown-user"), (False, 900)
            )
        with patch(
            "jireh.schools.login_budget.timezone.now",
            return_value=now + LOGIN_ATTEMPT_WINDOW + timedelta(seconds=1),
        ):
            self.assertEqual(
                charge_login_attempt(username="unknown-user"), (True, 0)
            )
        self.assertEqual(LoginAttemptBudget.objects.count(), 1)
        self.assertEqual(
            LoginAttemptBudget.objects.get().attempt_count, 1
        )

    def test_database_prevents_counter_exceeding_maximum(self):
        charge_login_attempt(username="family-login-parent")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                LoginAttemptBudget.objects.update(attempt_count=11)
        self.assertEqual(LoginAttemptBudget.objects.get().attempt_count, 1)

    def test_anonymous_logout_has_no_account_effect(self):
        client, csrf = self.new_client()
        response = client.post(
            self.logout_url(), HTTP_X_CSRFTOKEN=csrf
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"authenticated": False})
        self.assertFalse(LoginAttemptBudget.objects.exists())
