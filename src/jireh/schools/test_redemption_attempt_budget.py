"""Persistent redemption-throttle regression: account-wide, no token logging."""

import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .attempt_budget import (
    MAX_REDEMPTION_ATTEMPTS,
    REDEMPTION_WINDOW,
    charge_redemption_attempt,
)
from .models import Household, HouseholdAccess, RedemptionAttemptBudget, School


class RedemptionAttemptBudgetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.parent = User.objects.create_user(
            username="budget-parent", password="test-password"
        )
        cls.second_parent = User.objects.create_user(
            username="budget-second-parent", password="test-password"
        )
        cls.school = School.objects.create(code="budget-a", name="Budget School")
        cls.other_school = School.objects.create(
            code="budget-b", name="Other Budget School"
        )
        cls.household = Household.objects.create(
            school=cls.school, name="Budget Household"
        )
        cls.other_household = Household.objects.create(
            school=cls.other_school, name="Other Budget Household"
        )

    def url(self, *, other=False):
        school = self.other_school if other else self.school
        household = self.other_household if other else self.household
        return reverse(
            "jireh_test_household_redemption",
            kwargs={"school_id": school.pk, "household_id": household.pk},
        )

    def client_with_csrf(self, user=None):
        client = Client(enforce_csrf_checks=True)
        client.force_login(user or self.parent)
        response = client.get(self.url())
        self.assertEqual(response.status_code, 200)
        return client, client.cookies["csrftoken"].value

    def send(self, client, csrf, *, other=False, data=None):
        body = data if data is not None else json.dumps({
            "invitation_token": "a" * 64,
            "mailbox_token": "b" * 64,
        })
        return client.post(
            self.url(other=other),
            data=body,
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )

    def test_account_wide_limit_survives_new_sessions_and_school_urls(self):
        one, csrf1 = self.client_with_csrf()
        two, csrf2 = self.client_with_csrf()
        self.assertEqual(MAX_REDEMPTION_ATTEMPTS, 10)
        for i in range(10):
            client, csrf = (one, csrf1) if i % 2 == 0 else (two, csrf2)
            self.assertEqual(
                self.send(client, csrf, other=i % 3 == 0).status_code, 404
            )
        budget = RedemptionAttemptBudget.objects.get(user=self.parent)
        self.assertEqual(budget.attempt_count, 10)
        for client, csrf, other in (
            (one, csrf1, False), (two, csrf2, True),
        ):
            response = self.send(client, csrf, other=other)
            self.assertEqual(response.status_code, 429)
            self.assertEqual(
                response.json(), {"detail": "Too many redemption attempts."}
            )
            self.assertGreaterEqual(int(response["Retry-After"]), 1)
            self.assertLessEqual(int(response["Retry-After"]), 900)
            self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(
            RedemptionAttemptBudget.objects.get(user=self.parent).attempt_count,
            10,
        )
        self.assertEqual(HouseholdAccess.objects.count(), 0)

    def test_malformed_payload_counts_against_the_same_budget(self):
        client, csrf = self.client_with_csrf()
        for _ in range(10):
            response = self.send(client, csrf, data="{malformed")
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.send(client, csrf).status_code, 429)
        self.assertEqual(
            RedemptionAttemptBudget.objects.get(user=self.parent).attempt_count,
            10,
        )

    def test_limited_account_does_not_block_another_account(self):
        first, csrf1 = self.client_with_csrf()
        for _ in range(10):
            self.assertEqual(self.send(first, csrf1).status_code, 404)
        self.assertEqual(self.send(first, csrf1).status_code, 429)
        other, csrf2 = self.client_with_csrf(user=self.second_parent)
        self.assertEqual(self.send(other, csrf2).status_code, 404)
        self.assertEqual(
            RedemptionAttemptBudget.objects.get(
                user=self.second_parent
            ).attempt_count, 1
        )
        self.assertEqual(RedemptionAttemptBudget.objects.count(), 2)

    def test_window_expiry_resets_budget_without_new_record(self):
        now = timezone.now()
        with patch("jireh.schools.attempt_budget.timezone.now", return_value=now):
            for _ in range(10):
                self.assertEqual(
                    charge_redemption_attempt(user=self.parent), (True, 0)
                )
            allowed, retry = charge_redemption_attempt(user=self.parent)
            self.assertFalse(allowed)
            self.assertEqual(retry, 900)
        with patch(
            "jireh.schools.attempt_budget.timezone.now",
            return_value=now + REDEMPTION_WINDOW + timedelta(seconds=1),
        ):
            self.assertEqual(
                charge_redemption_attempt(user=self.parent), (True, 0)
            )
        budget = RedemptionAttemptBudget.objects.get(user=self.parent)
        self.assertEqual(budget.attempt_count, 1)
        self.assertEqual(RedemptionAttemptBudget.objects.count(), 1)

    def test_get_and_csrf_rejection_do_not_charge(self):
        client, _ = self.client_with_csrf()
        self.assertEqual(client.get(self.url()).status_code, 200)
        # Missing CSRF header is denied by Django before reaching the view.
        response = client.post(
            self.url(),
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(RedemptionAttemptBudget.objects.exists())

    def test_anonymous_user_cannot_create_budget(self):
        client = Client(enforce_csrf_checks=False)
        response = client.post(
            self.url(), data="{}", content_type="application/json"
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(RedemptionAttemptBudget.objects.exists())

    def test_inactive_account_is_rejected_without_billing_attempt(self):
        client, csrf = self.client_with_csrf()
        self.parent.is_active = False
        self.parent.save(update_fields=["is_active"])
        self.assertEqual(self.send(client, csrf).status_code, 403)
        self.assertFalse(RedemptionAttemptBudget.objects.exists())

    def test_database_rejects_counter_above_limit(self):
        charge_redemption_attempt(user=self.parent)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RedemptionAttemptBudget.objects.filter(user=self.parent).update(
                    attempt_count=MAX_REDEMPTION_ATTEMPTS + 1,
                )
        self.assertEqual(
            RedemptionAttemptBudget.objects.get(user=self.parent).attempt_count,
            1,
        )
