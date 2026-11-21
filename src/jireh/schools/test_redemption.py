"""Two-proof, authenticated, tenant-isolated, once-only redemption contracts."""

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

from .access import require_household_access
from .invitations import issue_household_invitation, revoke_household_invitation
from .models import (
    Household, HouseholdAccess, HouseholdInvitation, MailboxChallenge, School,
    SchoolInvitationEvent, SchoolStaffAccess,
)
from .redemption import (
    MAILBOX_PROOF_LIFETIME, issue_mailbox_challenge, redeem_household_invitation,
)


class InvitationRedemptionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.director = User.objects.create_user(username="redemption-director")
        cls.other_director = User.objects.create_user(
            username="redemption-other-director"
        )
        cls.parent = User.objects.create_user(
            username="redemption-parent", email="unrelated@example.invalid"
        )
        cls.other_parent = User.objects.create_user(
            username="redemption-other-parent"
        )
        cls.school = School.objects.create(
            code="redemption-a", name="Redemption School A"
        )
        cls.other_school = School.objects.create(
            code="redemption-b", name="Redemption School B"
        )
        cls.house = Household.objects.create(
            school=cls.school, name="Redemption Household"
        )
        cls.other_house = Household.objects.create(
            school=cls.other_school, name="Other Redemption Household"
        )
        SchoolStaffAccess.objects.create(
            school=cls.school, user=cls.director,
            role=SchoolStaffAccess.ROLE_AID_DIRECTOR
        )
        SchoolStaffAccess.objects.create(
            school=cls.other_school, user=cls.other_director,
            role=SchoolStaffAccess.ROLE_AID_DIRECTOR
        )

    def issue(self, **kwargs):
        params = dict(
            actor=self.director, school_id=self.school.pk,
            household_id=self.house.pk, email="family@example.org",
        )
        params.update(kwargs)
        return issue_household_invitation(**params)

    def proof(self, **kwargs):
        params = dict(user=self.parent, email="family@example.org")
        params.update(kwargs)
        return issue_mailbox_challenge(**params)

    def redeem(self, invite_token, proof_token, **kwargs):
        params = dict(
            user=self.parent, school_id=self.school.pk,
            household_id=self.house.pk, invitation_token=invite_token,
            mailbox_token=proof_token,
        )
        params.update(kwargs)
        return redeem_household_invitation(**params)

    def test_both_proofs_create_exact_scoped_grant_with_audit(self):
        invitation, secret = self.issue()
        proof, mailbox_secret = self.proof()
        self.assertEqual(MAILBOX_PROOF_LIFETIME, timedelta(minutes=15))
        self.assertEqual(
            proof.token_digest, hashlib.sha256(
                mailbox_secret.encode("ascii")
            ).hexdigest()
        )
        self.assertNotEqual(secret, mailbox_secret)
        self.assertEqual(HouseholdAccess.objects.count(), 0)
        grant = self.redeem(secret, mailbox_secret)
        self.assertEqual(grant.user_id, self.parent.pk)
        self.assertEqual(grant.household_id, self.house.pk)
        invitation.refresh_from_db()
        proof.refresh_from_db()
        self.assertIsNotNone(invitation.redeemed_at)
        self.assertEqual(invitation.redeemed_by_id, self.parent.pk)
        self.assertIsNotNone(proof.consumed_at)
        self.assertEqual(HouseholdAccess.objects.count(), 1)
        self.assertEqual(
            require_household_access(
                self.parent, school_id=self.school.pk, household_id=self.house.pk
            ).pk,
            self.house.pk,
        )
        with self.assertRaises(Http404):
            require_household_access(
                self.parent,
                school_id=self.other_school.pk,
                household_id=self.other_house.pk,
            )
        event = SchoolInvitationEvent.objects.get(action="REDEEMED")
        self.assertEqual(event.actor_user_id, self.parent.pk)
        self.assertEqual(event.school_id, self.school.pk)
        self.assertEqual(event.invitation_id, invitation.pk)

    def test_replay_fails_with_no_duplicate_grant_or_audit(self):
        invitation, secret = self.issue()
        proof, mailbox_secret = self.proof()
        self.redeem(secret, mailbox_secret)
        with self.assertRaises(Http404):
            self.redeem(secret, mailbox_secret)
        self.assertEqual(HouseholdAccess.objects.count(), 1)
        self.assertEqual(
            SchoolInvitationEvent.objects.filter(action="REDEEMED").count(), 1
        )

    def test_invitation_alone_does_not_grant_access(self):
        invitation, secret = self.issue()
        with self.assertRaises(Http404):
            self.redeem(secret, "a" * 64)
        self.assertEqual(HouseholdAccess.objects.count(), 0)
        self.assertIsNone(
            HouseholdInvitation.objects.get(pk=invitation.pk).redeemed_at
        )

    def test_mailbox_challenge_alone_does_not_grant_access(self):
        proof, mailbox_secret = self.proof()
        with self.assertRaises(Http404):
            self.redeem("b" * 64, mailbox_secret)
        self.assertEqual(HouseholdAccess.objects.count(), 0)
        self.assertIsNone(MailboxChallenge.objects.get(pk=proof.pk).consumed_at)

    def test_account_email_is_not_accepted_as_mailbox_proof(self):
        self.parent.email = "family@example.org"
        self.parent.save()
        invitation, secret = self.issue()
        with self.assertRaises(Http404):
            self.redeem(secret, "c" * 64)
        self.assertEqual(HouseholdAccess.objects.count(), 0)

    def test_other_account_cannot_redeem_using_both_secrets(self):
        _, secret = self.issue()
        proof, mailbox_secret = self.proof()
        with self.assertRaises(Http404):
            self.redeem(
                secret, mailbox_secret, user=self.other_parent
            )
        self.assertIsNone(MailboxChallenge.objects.get(pk=proof.pk).consumed_at)
        self.assertEqual(HouseholdAccess.objects.count(), 0)

    def test_wrong_email_proof_denied(self):
        _, secret = self.issue()
        _, mailbox_secret = self.proof(email="different@example.org")
        with self.assertRaises(Http404):
            self.redeem(secret, mailbox_secret)
        self.assertEqual(HouseholdAccess.objects.count(), 0)

    def test_anonymous_or_inactive_user_denied(self):
        _, secret = self.issue()
        _, mailbox_secret = self.proof()
        with self.assertRaises(PermissionDenied):
            self.redeem(secret, mailbox_secret, user=AnonymousUser())
        self.parent.is_active = False
        self.parent.save()
        with self.assertRaises(PermissionDenied):
            self.redeem(secret, mailbox_secret)
        self.assertEqual(HouseholdAccess.objects.count(), 0)

    def test_cross_school_and_household_scopes_are_denied(self):
        _, secret = self.issue()
        _, mailbox_secret = self.proof()
        for scope in (
            {"school_id": self.other_school.pk},
            {"household_id": self.other_house.pk},
            {"school_id": self.other_school.pk, "household_id": self.other_house.pk},
            {"school_id": None},
        ):
            with self.subTest(scope=scope):
                with self.assertRaises(Http404):
                    self.redeem(secret, mailbox_secret, **scope)
        self.assertEqual(HouseholdAccess.objects.count(), 0)

    def test_revoked_invitation_fails_closed(self):
        invitation, secret = self.issue()
        _, mailbox_secret = self.proof()
        revoke_household_invitation(
            actor=self.director, school_id=self.school.pk,
            invitation_id=invitation.pk,
        )
        with self.assertRaises(Http404):
            self.redeem(secret, mailbox_secret)
        self.assertEqual(HouseholdAccess.objects.count(), 0)

    def test_expired_invitation_fails_closed(self):
        invitation, secret = self.issue()
        _, mailbox_secret = self.proof()
        with patch(
            "jireh.schools.redemption.timezone.now",
            return_value=invitation.expires_at + timedelta(seconds=1),
        ):
            with self.assertRaises(Http404):
                self.redeem(secret, mailbox_secret)
        self.assertEqual(HouseholdAccess.objects.count(), 0)

    def test_expired_mailbox_challenge_fails_closed(self):
        _, secret = self.issue()
        proof, mailbox_secret = self.proof()
        with patch(
            "jireh.schools.redemption.timezone.now",
            return_value=proof.expires_at + timedelta(seconds=1),
        ):
            with self.assertRaises(Http404):
                self.redeem(secret, mailbox_secret)
        self.assertEqual(HouseholdAccess.objects.count(), 0)

    def test_invalid_token_shape_denied(self):
        _, secret = self.issue()
        _, mailbox_secret = self.proof()
        for invalid in ("", None, "short", "/" * 64, "x" * 65, 10):
            with self.subTest(invalid=invalid):
                with self.assertRaises(Http404):
                    self.redeem(invalid, mailbox_secret)
                with self.assertRaises(Http404):
                    self.redeem(secret, invalid)
        self.assertEqual(HouseholdAccess.objects.count(), 0)

    def test_existing_revoked_grant_is_never_reactivated(self):
        HouseholdAccess.objects.create(
            household=self.house, user=self.parent, is_active=False
        )
        _, secret = self.issue()
        proof, mailbox_secret = self.proof()
        with self.assertRaises(ValidationError):
            self.redeem(secret, mailbox_secret)
        self.assertFalse(HouseholdAccess.objects.get().is_active)
        self.assertIsNone(MailboxChallenge.objects.get(pk=proof.pk).consumed_at)
        self.assertEqual(
            SchoolInvitationEvent.objects.filter(action="REDEEMED").count(), 0
        )

    def test_redeemed_invitation_cannot_be_cancelled(self):
        invite, secret = self.issue()
        _, mailbox_secret = self.proof()
        self.redeem(secret, mailbox_secret)
        revoke_household_invitation(
            actor=self.director, school_id=self.school.pk,
            invitation_id=invite.pk,
        )
        invite.refresh_from_db()
        self.assertIsNone(invite.revoked_at)
        self.assertIsNotNone(invite.redeemed_at)

    def test_redeemed_invite_does_not_block_future_invitation(self):
        _, secret = self.issue()
        _, mailbox_secret = self.proof()
        self.redeem(secret, mailbox_secret)
        replacement, _ = self.issue()
        self.assertIsNone(replacement.redeemed_at)
        self.assertEqual(HouseholdInvitation.objects.count(), 2)

    def test_redeem_failure_rolls_back_proof_and_invitation(self):
        invitation, secret = self.issue()
        proof, mailbox_secret = self.proof()
        with patch.object(
            SchoolInvitationEvent.objects, "create",
            side_effect=RuntimeError("audit persistence failed"),
        ):
            with self.assertRaisesMessage(RuntimeError, "audit persistence failed"):
                self.redeem(secret, mailbox_secret)
        self.assertEqual(HouseholdAccess.objects.count(), 0)
        self.assertIsNone(
            HouseholdInvitation.objects.get(pk=invitation.pk).redeemed_at
        )
        self.assertIsNone(MailboxChallenge.objects.get(pk=proof.pk).consumed_at)

    def test_mailbox_challenge_reissue_after_expiration(self):
        proof, old = self.proof()
        with patch(
            "jireh.schools.redemption.timezone.now",
            return_value=proof.expires_at + timedelta(seconds=1),
        ):
            new_proof, new = self.proof()
        self.assertNotEqual(old, new)
        self.assertNotEqual(proof.pk, new_proof.pk)
        self.assertIsNotNone(
            MailboxChallenge.objects.get(pk=proof.pk).consumed_at
        )

    def test_mailbox_challenge_reissue_before_expiration_denied(self):
        self.proof()
        with self.assertRaises(ValidationError):
            self.proof()
        self.assertEqual(MailboxChallenge.objects.count(), 1)

    def test_invitation_and_proof_do_not_persist_raw_tokens(self):
        _, secret = self.issue()
        _, mailbox_secret = self.proof()
        persisted = repr(
            list(HouseholdInvitation.objects.values())
            + list(MailboxChallenge.objects.values())
            + list(SchoolInvitationEvent.objects.values())
        )
        self.assertNotIn(secret, persisted)
        self.assertNotIn(mailbox_secret, persisted)

    def test_postgresql_prevents_replay_mutation_and_cross_account_binding(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL-specific trigger integrity")
        invite, secret = self.issue()
        proof, mailbox_secret = self.proof()
        self.redeem(secret, mailbox_secret)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HouseholdInvitation.objects.filter(pk=invite.pk).update(
                    redeemed_at=None, redeemed_by=None,
                )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MailboxChallenge.objects.filter(pk=proof.pk).update(
                    consumed_at=None,
                )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MailboxChallenge.objects.filter(pk=proof.pk).update(
                    user_id=self.other_parent.pk,
                )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MailboxChallenge.objects.filter(pk=proof.pk).delete()

    def test_postgresql_mailbox_trigger_installed(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL-specific trigger integrity")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM pg_trigger "
                "WHERE tgname='jireh_mailbox_challenge_protect' "
                "AND NOT tgisinternal"
            )
            self.assertEqual(cursor.fetchone()[0], 1)
