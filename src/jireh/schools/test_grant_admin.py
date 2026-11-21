"""School-controlled, actor-attributed grant revocation; test-only services."""

from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.http import Http404
from django.test import TestCase

from .access import require_aid_director_access, require_household_access
from .grant_admin import revoke_household_access, revoke_staff_access
from .models import (
    GrantTransitionEvent,
    Household,
    HouseholdAccess,
    School,
    SchoolGrantDecisionEvent,
    SchoolStaffAccess,
)


class SchoolManagedRevocationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.director = User.objects.create_user(username="operator-a")
        cls.backup = User.objects.create_user(username="operator-backup")
        cls.other_director = User.objects.create_user(username="operator-b")
        cls.parent = User.objects.create_user(username="family-a")
        cls.other_parent = User.objects.create_user(username="family-b")
        cls.ordinary = User.objects.create_user(username="ordinary-user")
        cls.superuser = User.objects.create_superuser(
            username="root-without-grant",
            email="root@example.invalid",
            password="not-a-real-password",
        )
        cls.school = School.objects.create(code="operator-a", name="School A")
        cls.other_school = School.objects.create(code="operator-b", name="School B")
        cls.house = Household.objects.create(school=cls.school, name="Family A")
        cls.other_house = Household.objects.create(
            school=cls.other_school, name="Family B"
        )
        cls.family_grant = HouseholdAccess.objects.create(
            household=cls.house, user=cls.parent
        )
        cls.other_family_grant = HouseholdAccess.objects.create(
            household=cls.other_house, user=cls.other_parent
        )
        cls.staff = SchoolStaffAccess.objects.create(
            school=cls.school, user=cls.director,
            role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        )
        cls.backup_staff = SchoolStaffAccess.objects.create(
            school=cls.school, user=cls.backup,
            role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        )
        cls.other_staff = SchoolStaffAccess.objects.create(
            school=cls.other_school, user=cls.other_director,
            role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        )

    def family_revoke(self, **overrides):
        args = {
            "actor": self.director,
            "school_id": self.school.pk,
            "household_id": self.house.pk,
            "subject_user_id": self.parent.pk,
        }
        args.update(overrides)
        return revoke_household_access(**args)

    def staff_revoke(self, **overrides):
        args = {
            "actor": self.director,
            "school_id": self.school.pk,
            "subject_user_id": self.backup.pk,
        }
        args.update(overrides)
        return revoke_staff_access(**args)

    def test_director_revokes_own_school_family_and_records_real_actor(self):
        self.assertEqual(
            require_household_access(
                self.parent, school_id=self.school.pk,
                household_id=self.house.pk,
            ).pk, self.house.pk,
        )
        grant = self.family_revoke()
        self.assertFalse(grant.is_active)
        with self.assertRaises(Http404):
            require_household_access(
                self.parent, school_id=self.school.pk,
                household_id=self.house.pk,
            )
        event = SchoolGrantDecisionEvent.objects.get()
        self.assertEqual(event.school_id, self.school.pk)
        self.assertEqual(event.actor_user_id, self.director.pk)
        self.assertEqual(event.target_user_id, self.parent.pk)
        self.assertEqual(event.grant_kind, "HOUSEHOLD")
        self.assertEqual(event.grant_id, self.family_grant.pk)
        self.assertEqual(event.scope_id, self.house.pk)
        self.assertEqual(event.action, "REVOKED")

    def test_family_revocation_is_idempotent_without_duplicate_audit(self):
        self.family_revoke()
        self.family_revoke()
        self.assertEqual(SchoolGrantDecisionEvent.objects.count(), 1)
        self.assertEqual(HouseholdAccess.objects.count(), 2)

    def test_director_cannot_revoke_another_school_grant(self):
        with self.assertRaises(Http404):
            self.family_revoke(
                school_id=self.other_school.pk,
                household_id=self.other_house.pk,
                subject_user_id=self.other_parent.pk,
            )
        self.assertTrue(HouseholdAccess.objects.get(
            pk=self.other_family_grant.pk
        ).is_active)
        self.assertEqual(SchoolGrantDecisionEvent.objects.count(), 0)

    def test_forged_school_scope_cannot_retarget_a_household(self):
        with self.assertRaises(Http404):
            self.family_revoke(household_id=self.other_house.pk)
        self.assertTrue(HouseholdAccess.objects.get(
            pk=self.family_grant.pk
        ).is_active)

    def test_unknown_user_and_missing_scope_are_denied(self):
        for changes in (
            {"subject_user_id": 99999999},
            {"subject_user_id": None},
            {"household_id": None},
            {"household_id": uuid.uuid4()},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(Http404):
                    self.family_revoke(**changes)
        self.assertEqual(SchoolGrantDecisionEvent.objects.count(), 0)

    def test_non_directors_and_superusers_have_no_implicit_rights(self):
        for user in (self.parent, self.ordinary, self.superuser):
            with self.subTest(user=user.pk):
                with self.assertRaises(Http404):
                    self.family_revoke(actor=user)
        self.assertEqual(SchoolGrantDecisionEvent.objects.count(), 0)

    def test_anonymous_actor_is_denied(self):
        with self.assertRaises(PermissionDenied):
            self.family_revoke(actor=AnonymousUser())

    def test_inactive_director_is_denied(self):
        self.director.is_active = False
        self.director.save()
        with self.assertRaises(PermissionDenied):
            self.family_revoke()
        self.assertTrue(HouseholdAccess.objects.get(
            pk=self.family_grant.pk
        ).is_active)

    def test_revoked_director_cannot_administer_family_access(self):
        SchoolStaffAccess.objects.filter(pk=self.staff.pk).update(
            is_active=False
        )
        with self.assertRaises(Http404):
            self.family_revoke()
        self.assertEqual(SchoolGrantDecisionEvent.objects.count(), 0)

    def test_inactive_school_cannot_administer_access(self):
        self.school.is_active = False
        self.school.save()
        with self.assertRaises(Http404):
            self.family_revoke()
        self.assertTrue(HouseholdAccess.objects.get(
            pk=self.family_grant.pk
        ).is_active)

    def test_revoking_other_director_removes_rights_and_audits_actor(self):
        self.staff_revoke()
        with self.assertRaises(Http404):
            require_aid_director_access(self.backup, school_id=self.school.pk)
        self.assertEqual(
            require_aid_director_access(self.director, school_id=self.school.pk).pk,
            self.school.pk,
        )
        event = SchoolGrantDecisionEvent.objects.get()
        self.assertEqual(event.grant_kind, "STAFF")
        self.assertEqual(event.grant_id, self.backup_staff.pk)
        self.assertEqual(event.actor_user_id, self.director.pk)
        self.assertEqual(event.target_user_id, self.backup.pk)

    def test_staff_revocation_idempotent(self):
        self.staff_revoke()
        self.staff_revoke()
        self.assertEqual(SchoolGrantDecisionEvent.objects.count(), 1)

    def test_last_usable_director_cannot_be_revoked(self):
        self.staff_revoke()
        with self.assertRaisesMessage(ValidationError, "last active"):
            self.staff_revoke(subject_user_id=self.director.pk)
        self.assertTrue(SchoolStaffAccess.objects.get(
            pk=self.staff.pk
        ).is_active)
        self.assertEqual(SchoolGrantDecisionEvent.objects.count(), 1)

    def test_self_revocation_allowed_when_other_usable_director_remains(self):
        self.staff_revoke(subject_user_id=self.director.pk)
        with self.assertRaises(Http404):
            require_aid_director_access(self.director, school_id=self.school.pk)
        self.assertEqual(
            require_aid_director_access(self.backup, school_id=self.school.pk).pk,
            self.school.pk,
        )

    def test_inactive_backup_does_not_allow_last_director_revocation(self):
        self.backup.is_active = False
        self.backup.save()
        with self.assertRaisesMessage(ValidationError, "last active"):
            self.staff_revoke(subject_user_id=self.director.pk)
        self.assertTrue(SchoolStaffAccess.objects.get(
            pk=self.staff.pk
        ).is_active)

    def test_staff_cross_school_and_unknown_target_denied(self):
        for kwargs in (
            {"school_id": self.other_school.pk, "subject_user_id": self.other_director.pk},
            {"subject_user_id": self.other_director.pk},
            {"subject_user_id": 99999999},
            {"subject_user_id": None},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(Http404):
                    self.staff_revoke(**kwargs)
        self.assertTrue(SchoolStaffAccess.objects.get(
            pk=self.other_staff.pk
        ).is_active)
        self.assertEqual(SchoolGrantDecisionEvent.objects.count(), 0)

    def test_event_write_failure_rolls_back_grant_revocation(self):
        with patch.object(
            SchoolGrantDecisionEvent.objects, "create",
            side_effect=RuntimeError("Audit unavailable"),
        ):
            with self.assertRaisesMessage(RuntimeError, "Audit unavailable"):
                self.family_revoke()
        self.assertTrue(HouseholdAccess.objects.get(
            pk=self.family_grant.pk
        ).is_active)
        self.assertEqual(SchoolGrantDecisionEvent.objects.count(), 0)

    def test_event_model_is_append_only_for_ordinary_saves(self):
        self.family_revoke()
        event = SchoolGrantDecisionEvent.objects.get()
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            event.delete()

    def test_postgresql_event_append_only_and_db_transition_correlation(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL-only trigger guarantees.")
        self.family_revoke()
        event = SchoolGrantDecisionEvent.objects.get()
        transition = GrantTransitionEvent.objects.filter(
            school=self.school,
            grant_id=self.family_grant.pk,
            action=GrantTransitionEvent.ACTION_REVOKED,
        ).get()
        self.assertEqual(transition.subject_user_id, str(self.parent.pk))
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM pg_trigger WHERE "
                "tgname = 'jireh_school_grant_decision_append_only' "
                "AND NOT tgisinternal"
            )
            self.assertEqual(cursor.fetchone()[0], 1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SchoolGrantDecisionEvent.objects.filter(pk=event.pk).update(
                    action="REVOKED"
                )
        self.assertEqual(SchoolGrantDecisionEvent.objects.count(), 1)
