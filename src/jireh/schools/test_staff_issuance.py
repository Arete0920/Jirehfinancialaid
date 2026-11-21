"""Internal-only verified additional school director grants and audit."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.test import TestCase

from .access import require_aid_director_access
from .grant_admin import grant_additional_director, revoke_staff_access
from .models import (
    School, SchoolGrantDecisionEvent, SchoolStaffAccess,
    VerifiedRecoveryContact,
)
from .password_recovery import enroll_verified_recovery_contact
from .redemption import issue_mailbox_challenge


class AdditionalDirectorGrantTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.actor = User.objects.create_user(username="grant-actor")
        cls.target = User.objects.create_user(username="grant-target")
        cls.other = User.objects.create_user(username="grant-other")
        cls.unknown = User.objects.create_user(username="grant-unverified")
        cls.superuser = User.objects.create_superuser(
            username="grant-root", email="root@example.invalid",
            password="synthetic-password-only",
        )
        cls.school = School.objects.create(
            code="grant-staff-a", name="School A",
        )
        cls.other_school = School.objects.create(
            code="grant-staff-b", name="School B",
        )
        cls.actor_grant = SchoolStaffAccess.objects.create(
            school=cls.school,
            user=cls.actor,
            role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        )
        cls.other_grant = SchoolStaffAccess.objects.create(
            school=cls.other_school,
            user=cls.other,
            role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        )

    def verify_target(self, user=None):
        subject = user or self.target
        _, token = issue_mailbox_challenge(
            user=subject, email="staff-verified@example.org",
        )
        return enroll_verified_recovery_contact(
            user=subject,
            email="staff-verified@example.org",
            mailbox_token=token,
        )

    def grant(self, **overrides):
        args = {
            "actor": self.actor,
            "school_id": self.school.pk,
            "subject_user_id": self.target.pk,
        }
        args.update(overrides)
        return grant_additional_director(**args)

    def test_verified_subject_receives_only_one_school_scoped_grant(self):
        self.verify_target()
        grant = self.grant()
        self.assertTrue(grant.is_active)
        self.assertEqual(grant.role, SchoolStaffAccess.ROLE_AID_DIRECTOR)
        self.assertEqual(grant.school_id, self.school.pk)
        self.assertEqual(grant.user_id, self.target.pk)
        self.assertEqual(
            require_aid_director_access(
                self.target, school_id=self.school.pk
            ).pk,
            self.school.pk,
        )
        with self.assertRaises(Http404):
            require_aid_director_access(
                self.target, school_id=self.other_school.pk,
            )
        event = SchoolGrantDecisionEvent.objects.get()
        self.assertEqual(event.action, "CREATED")
        self.assertEqual(event.actor_user_id, self.actor.pk)
        self.assertEqual(event.target_user_id, self.target.pk)
        self.assertEqual(event.school_id, self.school.pk)
        self.assertEqual(event.grant_id, grant.pk)
        self.assertEqual(event.scope_id, self.school.pk)
        self.assertEqual(event.grant_kind, "STAFF")

    def test_existing_unverified_user_cannot_be_promoted(self):
        with self.assertRaisesMessage(ValidationError, "verified recovery"):
            self.grant()
        self.assertFalse(
            SchoolStaffAccess.objects.filter(user=self.target).exists()
        )
        self.assertFalse(SchoolGrantDecisionEvent.objects.exists())

    def test_user_email_alone_does_not_prove_mailbox_control(self):
        self.target.email = "staff-verified@example.org"
        self.target.save(update_fields=["email"])
        with self.assertRaises(ValidationError):
            self.grant()
        self.assertFalse(SchoolGrantDecisionEvent.objects.exists())

    def test_inactive_verified_user_cannot_be_promoted(self):
        self.verify_target()
        self.target.is_active = False
        self.target.save(update_fields=["is_active"])
        with self.assertRaises(Http404):
            self.grant()
        self.assertFalse(
            SchoolStaffAccess.objects.filter(user=self.target).exists()
        )

    def test_unknown_and_cross_school_scopes_are_denied(self):
        self.verify_target()
        for kwargs in (
            {"school_id": self.other_school.pk},
            {"subject_user_id": self.other.pk},
            {"subject_user_id": None},
            {"subject_user_id": 99999999},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises((Http404, ValidationError)):
                    self.grant(**kwargs)
        self.assertFalse(
            SchoolStaffAccess.objects.filter(user=self.target).exists()
        )

    def test_superuser_and_unassigned_user_do_not_bypass_director_check(self):
        self.verify_target()
        for subject in (self.superuser, self.unknown):
            with self.subTest(actor=subject.username):
                with self.assertRaises(Http404):
                    self.grant(actor=subject)
        with self.assertRaises(PermissionDenied):
            self.grant(actor=AnonymousUser())
        self.assertFalse(SchoolGrantDecisionEvent.objects.exists())

    def test_revoked_and_inactive_actor_cannot_issue_director_grants(self):
        self.verify_target()
        SchoolStaffAccess.objects.filter(pk=self.actor_grant.pk).update(
            is_active=False,
        )
        with self.assertRaises(Http404):
            self.grant()
        self.assertFalse(SchoolGrantDecisionEvent.objects.exists())

    def test_existing_staff_grant_cannot_be_duplicated_or_reactivated(self):
        self.verify_target()
        first = self.grant()
        with self.assertRaises(ValidationError):
            self.grant()
        revoke_staff_access(
            actor=self.actor,
            school_id=self.school.pk,
            subject_user_id=self.target.pk,
        )
        with self.assertRaises(ValidationError):
            self.grant()
        first.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertEqual(
            SchoolStaffAccess.objects.filter(
                school=self.school, user=self.target,
            ).count(),
            1,
        )
        self.assertEqual(
            set(SchoolGrantDecisionEvent.objects.values_list(
                "action", flat=True,
            )), {"CREATED", "REVOKED"},
        )

    def test_cannot_bootstrap_first_director(self):
        self.verify_target()
        SchoolStaffAccess.objects.filter(
            pk=self.actor_grant.pk,
        ).update(is_active=False)
        with self.assertRaises(Http404):
            self.grant()
        self.assertFalse(
            SchoolStaffAccess.objects.filter(
                school=self.school, user=self.target,
            ).exists()
        )

    def test_audit_insert_failure_rolls_back_new_privilege(self):
        self.verify_target()
        with patch.object(
            SchoolGrantDecisionEvent.objects,
            "create",
            side_effect=RuntimeError("audit unavailable"),
        ):
            with self.assertRaisesMessage(RuntimeError, "audit unavailable"):
                self.grant()
        self.assertFalse(
            SchoolStaffAccess.objects.filter(
                school=self.school, user=self.target,
            ).exists()
        )
        self.assertFalse(SchoolGrantDecisionEvent.objects.exists())

    def test_inactive_school_cannot_grant_staff(self):
        self.verify_target()
        self.school.is_active = False
        self.school.save(update_fields=["is_active"])
        with self.assertRaises(Http404):
            self.grant()
        self.assertFalse(SchoolGrantDecisionEvent.objects.exists())
