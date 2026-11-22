"""Durability regression tests for disabled-by-default first-director bootstrap.

TransactionTestCase is intentional: ordinary TestCase wraps the entire test
in an atomic block, hiding whether the attempt debit commits independently.
All users are disposable synthetic local test identities.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.test import TransactionTestCase

from .first_director_bootstrap import propose_first_director
from .models import LoginAttemptBudget, School


PASSWORD = "Synthetic-Operator-Durability-Password-2026!"


class BootstrapOperatorDurabilityTests(TransactionTestCase):
    def setUp(self):
        users = get_user_model()
        self.operator = users.objects.create_superuser(
            username="durable-operator-one",
            email="first@example.invalid",
            password=PASSWORD,
        )
        self.second = users.objects.create_superuser(
            username="durable-operator-two",
            email="second@example.invalid",
            password=PASSWORD,
        )
        self.school = School.objects.create(
            code="durable-school", name="Synthetic Durability School",
        )
        self.settings_guard = self.settings(
            JIREH_FIRST_DIRECTOR_BOOTSTRAP_ENABLED=True,
            JIREH_BOOTSTRAP_OPERATOR_IDS=(self.operator.pk, self.second.pk),
        )
        self.settings_guard.enable()
        self.addCleanup(self.settings_guard.disable)

    def propose(self, *, operator=None, password=PASSWORD, reference="BAD"):
        user = self.operator if operator is None else operator
        return propose_first_director(
            operator=user,
            operator_password=password,
            school_id=self.school.pk,
            subject_user_id=user.pk,
            authorization_reference=reference,
        )

    def test_failed_password_debit_survives_atomic_business_failure(self):
        self.assertFalse(transaction.get_connection().in_atomic_block)
        for _ in range(10):
            with self.assertRaises(PermissionDenied):
                self.propose(password="not-the-password", reference="VALID-REF-2026")
            self.assertFalse(transaction.get_connection().in_atomic_block)
        self.assertEqual(LoginAttemptBudget.objects.get().attempt_count, 10)
        with self.assertRaises(PermissionDenied):
            self.propose(reference="VALID-REF-2026")
        self.assertEqual(LoginAttemptBudget.objects.count(), 1)

    def test_validation_failure_does_not_rollback_attempt_counter(self):
        self.assertFalse(transaction.get_connection().in_atomic_block)
        with self.assertRaises(ValidationError):
            self.propose(reference="BAD")
        self.assertEqual(LoginAttemptBudget.objects.get().attempt_count, 1)
        self.assertFalse(transaction.get_connection().in_atomic_block)

    def test_outer_transaction_is_denied_without_record_mutation(self):
        with transaction.atomic():
            with self.assertRaises(PermissionDenied):
                self.propose(reference="BAD")
            self.assertFalse(LoginAttemptBudget.objects.exists())
        self.assertFalse(LoginAttemptBudget.objects.exists())

    def test_operator_budgets_are_independent(self):
        for operator in (self.operator, self.second):
            with self.assertRaises(PermissionDenied):
                self.propose(
                    operator=operator,
                    password="incorrect",
                    reference="VALID-REF-2026",
                )
        self.assertEqual(
            sorted(LoginAttemptBudget.objects.values_list("attempt_count", flat=True)),
            [1, 1],
        )
