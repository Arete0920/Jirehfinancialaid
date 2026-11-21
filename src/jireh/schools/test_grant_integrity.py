"""Django-level and PostgreSQL-backed immutable grant regression tests.

No test provisions a real account or grants permissions to a customer.
Grant activation/revocation authority, operator audit and RLS remain out of scope.
"""

import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.http import Http404
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from .access import require_aid_director_access, require_household_access
from .models import Household, HouseholdAccess, School, SchoolStaffAccess


class GrantModelIdentityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(
            username="parent"
        )
        cls.other_user = User.objects.create_user(
            username="different-user"
        )
        cls.school = School.objects.create(code="school-a", name="School A")
        cls.other_school = School.objects.create(code="school-b", name="School B")
        cls.household = Household.objects.create(
            school=cls.school, name="Household A"
        )
        cls.other_household = Household.objects.create(
            school=cls.other_school, name="Household B"
        )
        cls.family_grant = HouseholdAccess.objects.create(
            household=cls.household, user=cls.user
        )
        cls.staff_grant = SchoolStaffAccess.objects.create(
            school=cls.school, user=cls.user,
            role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        )

    def test_household_grant_cannot_change_household_on_instance(self):
        grant = HouseholdAccess.objects.get(pk=self.family_grant.pk)
        grant.household = self.other_household
        with self.assertRaises(ValidationError):
            grant.save()
        self.assertEqual(
            HouseholdAccess.objects.get(pk=self.family_grant.pk).household_id,
            self.household.pk,
        )

    def test_household_grant_cannot_change_user_on_instance(self):
        grant = HouseholdAccess.objects.get(pk=self.family_grant.pk)
        grant.user = self.other_user
        with self.assertRaises(ValidationError):
            grant.save()
        self.assertEqual(
            HouseholdAccess.objects.get(pk=self.family_grant.pk).user_id,
            self.user.pk,
        )

    def test_staff_grant_cannot_change_school_on_instance(self):
        grant = SchoolStaffAccess.objects.get(pk=self.staff_grant.pk)
        grant.school = self.other_school
        with self.assertRaises(ValidationError):
            grant.save()
        self.assertEqual(
            SchoolStaffAccess.objects.get(pk=self.staff_grant.pk).school_id,
            self.school.pk,
        )

    def test_staff_grant_cannot_change_user_or_role(self):
        for field, value in (
            ("user", self.other_user),
            ("role", "UNAPPROVED"),
        ):
            with self.subTest(field=field):
                grant = SchoolStaffAccess.objects.get(pk=self.staff_grant.pk)
                setattr(grant, field, value)
                with self.assertRaises(ValidationError):
                    grant.save()

    def test_persisted_grant_primary_key_cannot_be_changed(self):
        for model, pk in (
            (HouseholdAccess, self.family_grant.pk),
            (SchoolStaffAccess, self.staff_grant.pk),
        ):
            with self.subTest(model=model.__name__):
                grant = model.objects.get(pk=pk)
                grant.pk = uuid.uuid4()
                with self.assertRaises(ValidationError):
                    grant.save()
                self.assertEqual(model.objects.filter(pk=pk).count(), 1)

    def test_persisted_grant_creation_time_is_immutable(self):
        grant = HouseholdAccess.objects.get(pk=self.family_grant.pk)
        grant.created_at -= timedelta(days=1)
        with self.assertRaises(ValidationError):
            grant.save()

    def test_model_instance_deletion_is_rejected(self):
        for model, pk in (
            (HouseholdAccess, self.family_grant.pk),
            (SchoolStaffAccess, self.staff_grant.pk),
        ):
            with self.subTest(model=model.__name__):
                with self.assertRaises(ValidationError):
                    model.objects.get(pk=pk).delete()
                self.assertTrue(model.objects.filter(pk=pk).exists())

    def test_revocation_is_allowed_and_revokes_effective_access(self):
        household_grant = HouseholdAccess.objects.get(pk=self.family_grant.pk)
        staff_grant = SchoolStaffAccess.objects.get(pk=self.staff_grant.pk)
        self.assertEqual(
            require_household_access(
                self.user, school_id=self.school.pk,
                household_id=self.household.pk,
            ).pk, self.household.pk,
        )
        self.assertEqual(
            require_aid_director_access(
                self.user, school_id=self.school.pk,
            ).pk, self.school.pk,
        )
        household_grant.is_active = False
        household_grant.save()
        staff_grant.is_active = False
        staff_grant.save()
        with self.assertRaises(Http404):
            require_household_access(
                self.user, school_id=self.school.pk,
                household_id=self.household.pk,
            )
        with self.assertRaises(Http404):
            require_aid_director_access(
                self.user, school_id=self.school.pk,
            )
        self.assertEqual(HouseholdAccess.objects.count(), 1)
        self.assertEqual(SchoolStaffAccess.objects.count(), 1)


class PostgreSQLGrantIdentityTests(TransactionTestCase):
    """Verify actual PG guard triggers; SQLite is not covered by SQL guards."""

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL-only database integrity tests")
        User = get_user_model()
        self.user = User.objects.create_user(
            username="pg-principal"
        )
        self.other_user = User.objects.create_user(
            username="pg-other-principal"
        )
        self.school = School.objects.create(code="pg-a", name="PG School A")
        self.other_school = School.objects.create(
            code="pg-b", name="PG School B"
        )
        self.household = Household.objects.create(
            school=self.school, name="PG Household A"
        )
        self.other_household = Household.objects.create(
            school=self.other_school, name="PG Household B"
        )
        self.household_grant = HouseholdAccess.objects.create(
            household=self.household, user=self.user
        )
        self.staff_grant = SchoolStaffAccess.objects.create(
            school=self.school, user=self.user,
            role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        )

    def _assert_guard_rejects(self, queryset, **update_fields):
        with self.assertRaisesMessage(IntegrityError, "grant binding is immutable"):
            with transaction.atomic():
                queryset.update(**update_fields)

    def test_postgresql_installed_two_grant_triggers(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM pg_trigger "
                "WHERE tgname IN ("
                "'jireh_household_access_identity_protect', "
                "'jireh_school_staff_access_identity_protect') "
                "AND NOT tgisinternal"
            )
            count = cursor.fetchone()[0]
        self.assertEqual(count, 2)

    def test_raw_household_grant_cannot_move_to_new_user_or_household(self):
        original = HouseholdAccess.objects.filter(pk=self.household_grant.pk)
        for mutation in (
            {"user_id": self.other_user.pk},
            {"household_id": self.other_household.pk},
        ):
            with self.subTest(mutation=mutation):
                self._assert_guard_rejects(original, **mutation)
        saved = HouseholdAccess.objects.get(pk=self.household_grant.pk)
        self.assertEqual(saved.user_id, self.user.pk)
        self.assertEqual(saved.household_id, self.household.pk)

    def test_raw_staff_grant_cannot_move_to_other_school_or_user(self):
        original = SchoolStaffAccess.objects.filter(pk=self.staff_grant.pk)
        for mutation in (
            {"user_id": self.other_user.pk},
            {"school_id": self.other_school.pk},
            {"role": "SUPPORT"},
        ):
            with self.subTest(mutation=mutation):
                self._assert_guard_rejects(original, **mutation)
        saved = SchoolStaffAccess.objects.get(pk=self.staff_grant.pk)
        self.assertEqual(saved.user_id, self.user.pk)
        self.assertEqual(saved.school_id, self.school.pk)
        self.assertEqual(saved.role, "AID_DIRECTOR")

    def test_grant_primary_key_and_creation_timestamp_protected(self):
        for model, pk in (
            (HouseholdAccess, self.household_grant.pk),
            (SchoolStaffAccess, self.staff_grant.pk),
        ):
            for mutation in (
                {"id": uuid.uuid4()},
                {"created_at": timezone.now() - timedelta(days=1)},
            ):
                with self.subTest(model=model.__name__, mutation=mutation):
                    with self.assertRaisesMessage(
                        IntegrityError, "existing grant identity is immutable"
                    ):
                        with transaction.atomic():
                            model.objects.filter(pk=pk).update(**mutation)
                self.assertTrue(model.objects.filter(pk=pk).exists())

    def test_raw_queryset_grant_deletion_is_rejected(self):
        for model, pk in (
            (HouseholdAccess, self.household_grant.pk),
            (SchoolStaffAccess, self.staff_grant.pk),
        ):
            with self.subTest(model=model.__name__):
                with self.assertRaisesMessage(
                    IntegrityError, "grants cannot be deleted"
                ):
                    with transaction.atomic():
                        model.objects.filter(pk=pk).delete()
                self.assertEqual(model.objects.filter(pk=pk).count(), 1)

    def test_bulk_revocation_allowed_but_identity_unchanged(self):
        self.assertEqual(
            HouseholdAccess.objects.filter(pk=self.household_grant.pk).update(
                is_active=False
            ), 1,
        )
        self.assertEqual(
            SchoolStaffAccess.objects.filter(pk=self.staff_grant.pk).update(
                is_active=False
            ), 1,
        )
        with self.assertRaises(Http404):
            require_household_access(
                self.user, school_id=self.school.pk,
                household_id=self.household.pk,
            )
        with self.assertRaises(Http404):
            require_aid_director_access(
                self.user, school_id=self.school.pk,
            )
        self.assertFalse(HouseholdAccess.objects.get(
            pk=self.household_grant.pk
        ).is_active)
        self.assertFalse(SchoolStaffAccess.objects.get(
            pk=self.staff_grant.pk
        ).is_active)
