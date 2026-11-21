"""Pending-only household invitations: school isolation, secrecy, audit and PG guards."""

import hashlib
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.http import Http404
from django.test import TestCase
from django.utils import timezone

from .invitations import (
    INVITATION_LIFETIME,
    issue_household_invitation,
    revoke_household_invitation,
)
from .models import (
    Household, HouseholdAccess, HouseholdInvitation,
    School, SchoolInvitationEvent, SchoolStaffAccess,
)


class HouseholdInvitationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.director = User.objects.create_user(username="invite-director")
        cls.other_director = User.objects.create_user(username="invite-other")
        cls.unauthorized = User.objects.create_user(username="invite-ordinary")
        cls.parent = User.objects.create_user(username="invite-family")
        cls.superuser = User.objects.create_superuser(
            username="invite-superuser",
            email="admin@example.invalid",
            password="not-a-real-password",
        )
        cls.school = School.objects.create(code="invite-a", name="Invitation A")
        cls.other_school = School.objects.create(
            code="invite-b", name="Invitation B"
        )
        cls.household = Household.objects.create(
            school=cls.school, name="First household"
        )
        cls.second_household = Household.objects.create(
            school=cls.school, name="Second household"
        )
        cls.other_household = Household.objects.create(
            school=cls.other_school, name="Other school family"
        )
        SchoolStaffAccess.objects.create(
            school=cls.school, user=cls.director,
            role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        )
        SchoolStaffAccess.objects.create(
            school=cls.other_school, user=cls.other_director,
            role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        )

    def issue(self, **kwargs):
        args = dict(
            actor=self.director, school_id=self.school.pk,
            household_id=self.household.pk, email="Parent@Example.org ",
        )
        args.update(kwargs)
        return issue_household_invitation(**args)

    def revoke(self, invitation, **kwargs):
        args = dict(
            actor=self.director, school_id=self.school.pk,
            invitation_id=invitation.pk,
        )
        args.update(kwargs)
        return revoke_household_invitation(**args)

    def test_school_director_issues_opaque_pending_invitation_without_grant(self):
        before = timezone.now()
        invitation, token = self.issue()
        self.assertEqual(invitation.school_id, self.school.pk)
        self.assertEqual(invitation.household_id, self.household.pk)
        self.assertEqual(invitation.email, "parent@example.org")
        self.assertEqual(invitation.invited_by_id, self.director.pk)
        self.assertEqual(len(token) >= 64, True)
        self.assertNotEqual(invitation.token_digest, token)
        self.assertEqual(
            invitation.token_digest,
            hashlib.sha256(token.encode("ascii")).hexdigest(),
        )
        self.assertLessEqual(
            invitation.expires_at, before + INVITATION_LIFETIME + timedelta(seconds=5)
        )
        self.assertEqual(HouseholdAccess.objects.count(), 0)
        events = list(SchoolInvitationEvent.objects.all())
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action, "ISSUED")
        self.assertEqual(events[0].actor_user_id, self.director.pk)
        self.assertEqual(events[0].school_id, self.school.pk)

    def test_raw_token_is_not_in_persisted_record_or_audit(self):
        invitation, secret = self.issue()
        persisted = repr(
            list(HouseholdInvitation.objects.values())
            + list(SchoolInvitationEvent.objects.values())
        )
        self.assertNotIn(secret, persisted)
        self.assertNotIn(secret, str(invitation))

    def test_duplicate_pending_recipient_is_rejected_without_new_secret(self):
        self.issue()
        with self.assertRaises(ValidationError):
            self.issue(email="PARENT@example.org")
        self.assertEqual(HouseholdInvitation.objects.count(), 1)
        self.assertEqual(SchoolInvitationEvent.objects.count(), 1)

    def test_director_can_cancel_pending_invite_and_reissue(self):
        invitation, previous_secret = self.issue()
        self.revoke(invitation)
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.revoked_at)
        self.revoke(invitation)
        self.assertEqual(
            list(
                SchoolInvitationEvent.objects.filter(
                    invitation=invitation
                ).values_list("action", flat=True)
            ),
            ["ISSUED", "REVOKED"],
        )
        replacement, new_secret = self.issue()
        self.assertNotEqual(replacement.pk, invitation.pk)
        self.assertNotEqual(new_secret, previous_secret)
        self.assertIsNone(replacement.revoked_at)
        self.assertEqual(HouseholdAccess.objects.count(), 0)

    def test_expired_pending_invite_is_revoked_and_replaced_atomically(self):
        old, old_secret = self.issue()
        after_expiry = old.expires_at + timedelta(seconds=1)
        with patch("jireh.schools.invitations.timezone.now", return_value=after_expiry):
            replacement, new_secret = self.issue()
        old.refresh_from_db()
        self.assertEqual(old.revoked_at, after_expiry)
        self.assertNotEqual(new_secret, old_secret)
        self.assertEqual(replacement.email, old.email)
        self.assertEqual(
            list(SchoolInvitationEvent.objects.filter(
                invitation=old,
            ).values_list("action", flat=True).order_by("action")),
            ["ISSUED", "REVOKED"],
        )
        self.assertEqual(HouseholdAccess.objects.count(), 0)

    def test_invite_can_target_different_households_independently(self):
        first, _ = self.issue()
        second, _ = self.issue(household_id=self.second_household.pk)
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(HouseholdInvitation.objects.count(), 2)

    def test_other_school_scope_and_household_spoofing_are_denied(self):
        for args in (
            dict(school_id=self.other_school.pk),
            dict(household_id=self.other_household.pk),
            dict(school_id=self.other_school.pk, household_id=self.other_household.pk),
            dict(household_id=None),
        ):
            with self.subTest(args=args):
                with self.assertRaises(Http404):
                    self.issue(**args)
        self.assertEqual(HouseholdInvitation.objects.count(), 0)

    def test_anonymous_and_non_director_are_denied(self):
        with self.assertRaises(PermissionDenied):
            self.issue(actor=AnonymousUser())
        for user in (self.unauthorized, self.parent, self.superuser):
            with self.subTest(user=user.pk):
                with self.assertRaises(Http404):
                    self.issue(actor=user)
        self.assertEqual(HouseholdInvitation.objects.count(), 0)

    def test_inactive_director_or_revoked_director_denied(self):
        self.director.is_active = False
        self.director.save()
        with self.assertRaises(PermissionDenied):
            self.issue()
        self.director.is_active = True
        self.director.save()
        SchoolStaffAccess.objects.filter(user=self.director).update(is_active=False)
        with self.assertRaises(Http404):
            self.issue()

    def test_inactive_school_and_household_denied(self):
        self.school.is_active = False
        self.school.save()
        with self.assertRaises(Http404):
            self.issue()
        self.school.is_active = True
        self.school.save()
        self.household.is_active = False
        self.household.save()
        with self.assertRaises(Http404):
            self.issue()

    def test_invalid_email_is_rejected_without_persisting(self):
        for bad in ("", "not-an-email", "invalid@@example.org", "a" * 255, None):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    self.issue(email=bad)
        self.assertEqual(HouseholdInvitation.objects.count(), 0)

    def test_cannot_cancel_other_school_invitation(self):
        invite, _ = issue_household_invitation(
            actor=self.other_director, school_id=self.other_school.pk,
            household_id=self.other_household.pk, email="other@example.org",
        )
        with self.assertRaises(Http404):
            self.revoke(invite)
        self.assertIsNone(HouseholdInvitation.objects.get(pk=invite.pk).revoked_at)

    def test_unauthorized_cancellation_is_denied(self):
        invitation, _ = self.issue()
        with self.assertRaises(Http404):
            self.revoke(invitation, actor=self.unauthorized)
        self.assertIsNone(HouseholdInvitation.objects.get(pk=invitation.pk).revoked_at)

    def test_unknown_invitation_cancellation_is_denied(self):
        with self.assertRaises(Http404):
            revoke_household_invitation(
                actor=self.director,
                school_id=self.school.pk,
                invitation_id=None,
            )

    def test_audit_failure_rolls_back_issue_and_cancel(self):
        with patch.object(
            SchoolInvitationEvent.objects, "create",
            side_effect=RuntimeError("audit unavailable"),
        ):
            with self.assertRaisesMessage(RuntimeError, "audit unavailable"):
                self.issue()
        self.assertEqual(HouseholdInvitation.objects.count(), 0)
        invitation, _ = self.issue()
        with patch.object(
            SchoolInvitationEvent.objects, "create",
            side_effect=RuntimeError("audit unavailable"),
        ):
            with self.assertRaisesMessage(RuntimeError, "audit unavailable"):
                self.revoke(invitation)
        self.assertIsNone(HouseholdInvitation.objects.get(pk=invitation.pk).revoked_at)
        self.assertEqual(SchoolInvitationEvent.objects.count(), 1)

    def test_models_cannot_reassign_invitation_or_modify_audit(self):
        invite, _ = self.issue()
        invite.email = "changed@example.org"
        with self.assertRaises(ValidationError):
            invite.save()
        with self.assertRaises(ValidationError):
            invite.delete()
        event = SchoolInvitationEvent.objects.get()
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            event.delete()

    def test_model_rejects_cross_school_invitation(self):
        with self.assertRaises(ValidationError):
            HouseholdInvitation.objects.create(
                school=self.other_school,
                household=self.household,
                invited_by=self.other_director,
                email="cross@example.org",
                expires_at=timezone.now() + INVITATION_LIFETIME,
                token_digest="d" * 64,
            )

    def test_postgresql_triggers_guard_raw_changes(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL 16 trigger enforcement required.")
        invitation, _ = self.issue()
        event = SchoolInvitationEvent.objects.get()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM pg_trigger WHERE tgname IN "
                "('jireh_invitation_identity_protect', "
                "'jireh_invitation_delete_protect', "
                "'jireh_invitation_event_protect') AND NOT tgisinternal"
            )
            self.assertEqual(cursor.fetchone()[0], 3)
        for query, mutation in (
            (HouseholdInvitation.objects.filter(pk=invitation.pk),
             {"household_id": self.other_household.pk}),
            (HouseholdInvitation.objects.filter(pk=invitation.pk),
             {"token_digest": "e" * 64}),
            (SchoolInvitationEvent.objects.filter(pk=event.pk),
             {"action": "REVOKED"}),
        ):
            with self.subTest(mutation=mutation):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        query.update(**mutation)
        self.assertEqual(HouseholdInvitation.objects.count(), 1)
        self.assertEqual(SchoolInvitationEvent.objects.count(), 1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HouseholdInvitation.objects.filter(pk=invitation.pk).delete()

    def test_postgresql_rejected_reactivation_and_cross_school_audit(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL 16 trigger enforcement required.")
        invitation, _ = self.issue()
        # Create a forged REVOKED event while the only real event is ISSUED.
        # This avoids an unrelated uniqueness violation masking the scope guard.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SchoolInvitationEvent.objects.bulk_create([
                    SchoolInvitationEvent(
                        school=self.other_school,
                        invitation=invitation,
                        actor_user=self.other_director,
                        action="REVOKED",
                    )
                ])
        self.revoke(invitation)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HouseholdInvitation.objects.filter(pk=invitation.pk).update(
                    revoked_at=None,
                )
        self.assertEqual(
            SchoolInvitationEvent.objects.filter(invitation=invitation).count(), 2
        )
