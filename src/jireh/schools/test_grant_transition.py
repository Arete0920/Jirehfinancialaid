"""PostgreSQL-only grant transition evidence; no human identity inferred.

Every grant INSERT and active-state transition is captured in PostgreSQL,
including QuerySet.update(), without giving anyone new authorization.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.http import Http404
from django.test import TestCase, TransactionTestCase

from .access import require_household_access
from .models import (
    GrantTransitionEvent, Household, HouseholdAccess,
    School, SchoolStaffAccess,
)


class GrantTransitionModelSafetyTests(TestCase):
    def test_models_cannot_forge_events_through_save(self):
        with self.assertRaises(ValidationError):
            GrantTransitionEvent().save()

    def test_events_cannot_be_deleted_as_model_instances(self):
        with self.assertRaises(ValidationError):
            GrantTransitionEvent().delete()

    def test_scope_query_requires_explicit_school(self):
        with self.assertRaises(ValueError):
            GrantTransitionEvent.objects.for_school(None)


class PostgreSQLGrantTransitionTests(TransactionTestCase):
    """These tests must actually run on PostgreSQL 16, never SQLite."""

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Grant transition capture requires PostgreSQL.")
        User = get_user_model()
        self.user = User.objects.create_user(username="grant-history-user")
        self.other_user = User.objects.create_user(username="grant-history-other")
        self.school = School.objects.create(
            code="grant-history-school", name="History School"
        )
        self.other_school = School.objects.create(
            code="grant-history-other-school", name="Other School"
        )
        self.household = Household.objects.create(
            school=self.school, name="History Household"
        )
        self.family = HouseholdAccess.objects.create(
            household=self.household, user=self.user
        )
        self.staff = SchoolStaffAccess.objects.create(
            school=self.school, user=self.user,
            role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        )

    def _events(self, kind):
        return list(
            GrantTransitionEvent.objects.for_school(self.school.pk)
            .filter(grant_kind=kind)
            .order_by("created_at", "id")
        )

    def test_three_transition_triggers_are_installed(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM pg_trigger "
                "WHERE tgname IN ("
                "'jireh_household_grant_transition_capture', "
                "'jireh_staff_grant_transition_capture', "
                "'jireh_grant_transition_append_only') "
                "AND NOT tgisinternal"
            )
            count = cursor.fetchone()[0]
        self.assertEqual(count, 3)

    def test_create_events_record_scope_user_role_and_timestamp(self):
        family_events = self._events(GrantTransitionEvent.KIND_HOUSEHOLD)
        staff_events = self._events(GrantTransitionEvent.KIND_STAFF)
        self.assertEqual(len(family_events), 1)
        self.assertEqual(len(staff_events), 1)
        with connection.cursor() as cursor:
            cursor.execute("SELECT CURRENT_USER")
            db_role = cursor.fetchone()[0]
        for event, grant, scope in (
            (family_events[0], self.family, self.household.pk),
            (staff_events[0], self.staff, self.school.pk),
        ):
            with self.subTest(grant=grant.pk):
                self.assertEqual(event.action, "CREATED")
                self.assertEqual(event.grant_id, grant.pk)
                self.assertEqual(event.school_id, self.school.pk)
                self.assertEqual(event.scope_id, scope)
                self.assertEqual(event.subject_user_id, str(self.user.pk))
                self.assertEqual(event.database_role, db_role)
                self.assertTrue(event.is_active)
                self.assertIsNotNone(event.created_at)

    def test_created_inactive_grant_records_inactive_creation(self):
        grant = HouseholdAccess.objects.create(
            household=self.household, user=self.other_user, is_active=False
        )
        event = GrantTransitionEvent.objects.get(
            grant_id=grant.pk, action="CREATED"
        )
        self.assertFalse(event.is_active)
        self.assertEqual(event.subject_user_id, str(self.other_user.pk))
        self.assertEqual(
            GrantTransitionEvent.objects.filter(grant_id=grant.pk).count(), 1
        )

    def test_bulk_revoke_and_reactivate_emit_exact_transitions(self):
        for model, grant, kind in (
            (HouseholdAccess, self.family, "HOUSEHOLD"),
            (SchoolStaffAccess, self.staff, "STAFF"),
        ):
            with self.subTest(kind=kind):
                self.assertEqual(
                    model.objects.filter(pk=grant.pk).update(is_active=False),
                    1,
                )
                self.assertEqual(
                    model.objects.filter(pk=grant.pk).update(is_active=True),
                    1,
                )
                actions = list(
                    GrantTransitionEvent.objects.filter(grant_id=grant.pk)
                    .order_by("created_at", "id")
                    .values_list("action", "is_active")
                )
                self.assertEqual(
                    actions,
                    [
                        ("CREATED", True),
                        ("REVOKED", False),
                        ("REACTIVATED", True),
                    ],
                )

    def test_revocation_audit_is_atomic_with_loss_of_access(self):
        self.assertEqual(
            require_household_access(
                self.user, school_id=self.school.pk,
                household_id=self.household.pk,
            ).pk,
            self.household.pk,
        )
        HouseholdAccess.objects.filter(pk=self.family.pk).update(
            is_active=False
        )
        with self.assertRaises(Http404):
            require_household_access(
                self.user, school_id=self.school.pk,
                household_id=self.household.pk,
            )
        event = GrantTransitionEvent.objects.get(
            grant_id=self.family.pk, action="REVOKED"
        )
        self.assertFalse(event.is_active)
        self.assertEqual(event.school_id, self.school.pk)

    def test_noop_is_active_update_and_nonstatus_edit_do_not_log(self):
        HouseholdAccess.objects.filter(pk=self.family.pk).update(
            is_active=True
        )
        HouseholdAccess.objects.filter(pk=self.family.pk).update(
            updated_at=self.family.updated_at
        )
        self.assertEqual(
            GrantTransitionEvent.objects.filter(grant_id=self.family.pk).count(),
            1,
        )

    def test_status_change_rollback_removes_uncommitted_event(self):
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with transaction.atomic():
                HouseholdAccess.objects.filter(pk=self.family.pk).update(
                    is_active=False
                )
                self.assertEqual(
                    GrantTransitionEvent.objects.filter(
                        grant_id=self.family.pk
                    ).count(), 2,
                )
                raise RuntimeError("rollback")
        self.assertTrue(
            HouseholdAccess.objects.get(pk=self.family.pk).is_active
        )
        self.assertEqual(
            GrantTransitionEvent.objects.filter(grant_id=self.family.pk).count(),
            1,
        )

    def test_failed_identity_reassignment_does_not_log_new_event(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HouseholdAccess.objects.filter(pk=self.family.pk).update(
                    user_id=self.other_user.pk
                )
        self.assertEqual(
            GrantTransitionEvent.objects.filter(grant_id=self.family.pk).count(),
            1,
        )
        self.assertEqual(
            HouseholdAccess.objects.get(pk=self.family.pk).user_id,
            self.user.pk,
        )

    def test_database_rejects_audit_update_and_delete(self):
        event = self._events("HOUSEHOLD")[0]
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                GrantTransitionEvent.objects.filter(pk=event.pk).update(
                    action="REVOKED"
                )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                GrantTransitionEvent.objects.filter(pk=event.pk).delete()
        self.assertEqual(
            GrantTransitionEvent.objects.get(pk=event.pk).action,
            "CREATED",
        )

    def test_school_scope_never_reads_other_school_events(self):
        second_household = Household.objects.create(
            school=self.other_school, name="Other School Household"
        )
        HouseholdAccess.objects.create(
            household=second_household, user=self.other_user
        )
        self.assertEqual(
            GrantTransitionEvent.objects.for_school(self.school.pk).count(),
            2,
        )
        self.assertEqual(
            GrantTransitionEvent.objects.for_school(
                self.other_school.pk
            ).count(),
            1,
        )
