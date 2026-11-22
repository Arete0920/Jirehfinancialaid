"""First-director dual-control bootstrap. Disposable synthetic accounts only."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.http import Http404
from django.test import TestCase
from django.utils import timezone

from .access import require_aid_director_access
from .first_director_bootstrap import (
    approve_first_director, propose_first_director,
)
from .models import (
    FirstDirectorBootstrapRequest, LoginAttemptBudget, School, SchoolGrantDecisionEvent,
    SchoolStaffAccess,
)
from .password_recovery import enroll_verified_recovery_contact
from .redemption import issue_mailbox_challenge


PASSWORD = "Synthetic-Independent-Operator-Password-23456!"
REFERENCE = "SCHOOL-AUTHORIZATION-2026-001"


class FirstDirectorBootstrapTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.proposer = User.objects.create_superuser(
            username="bootstrap-proposer", email="operator1@example.invalid",
            password=PASSWORD,
        )
        cls.approver = User.objects.create_superuser(
            username="bootstrap-approver", email="operator2@example.invalid",
            password=PASSWORD,
        )
        cls.third = User.objects.create_superuser(
            username="bootstrap-unauthorized", email="operator3@example.invalid",
            password=PASSWORD,
        )
        cls.subject = User.objects.create_user(
            username="bootstrap-subject", password=PASSWORD,
        )
        cls.other_subject = User.objects.create_user(
            username="bootstrap-other-subject", password=PASSWORD,
        )
        cls.school = School.objects.create(code="bootstrap-school", name="School One")
        cls.other_school = School.objects.create(
            code="bootstrap-other-school", name="School Two",
        )

    def setUp(self):
        settings_context = self.settings(
            JIREH_FIRST_DIRECTOR_BOOTSTRAP_ENABLED=True,
            JIREH_BOOTSTRAP_OPERATOR_IDS=(
                self.proposer.pk, self.approver.pk,
            ),
        )
        settings_context.enable()
        self.addCleanup(settings_context.disable)
        # Legacy tests isolate school/dual-control rules. The real synthetic
        # cryptographic MFA boundary is tested in test_first_director_mfa.py.
        mfa_patch = patch(
            "jireh.schools.first_director_bootstrap.consume_director_action_proof",
            return_value=None,
        )
        mfa_patch.start()
        self.addCleanup(mfa_patch.stop)

    def verify(self, user=None):
        user = user or self.subject
        _, token = issue_mailbox_challenge(
            user=user, email="synthetic-verified@example.org",
        )
        return enroll_verified_recovery_contact(
            user=user, email="synthetic-verified@example.org",
            mailbox_token=token,
        )

    def propose(self, **kw):
        args = {
            "operator": self.proposer,
            "operator_password": PASSWORD,
            "school_id": self.school.pk,
            "subject_user_id": self.subject.pk,
            "authorization_reference": REFERENCE,
        }
        args.update(kw)
        return propose_first_director(**args)

    def approve(self, request, **kw):
        args = {
            "operator": self.approver,
            "operator_password": PASSWORD,
            "request_id": request.pk,
            "authorization_reference": REFERENCE,
        }
        args.update(kw)
        return approve_first_director(**args)

    def test_two_distinct_operators_can_approve_first_director_only(self):
        self.verify()
        proposal = self.propose()
        self.assertIsNone(proposal.approved_at)
        self.assertEqual(proposal.proposed_by_id, self.proposer.pk)
        self.assertEqual(proposal.authorization_reference, REFERENCE)
        self.assertEqual(SchoolStaffAccess.objects.count(), 0)
        with self.assertRaises(Http404):
            require_aid_director_access(
                self.subject, school_id=self.school.pk,
            )

        grant = self.approve(proposal)
        self.assertEqual(grant.school_id, self.school.pk)
        self.assertEqual(grant.user_id, self.subject.pk)
        self.assertTrue(grant.is_active)
        proposal.refresh_from_db()
        self.assertEqual(proposal.approved_by_id, self.approver.pk)
        self.assertEqual(proposal.grant_id, grant.pk)
        self.assertIsNotNone(proposal.approved_at)
        self.assertEqual(
            require_aid_director_access(
                self.subject, school_id=self.school.pk,
            ).pk,
            self.school.pk,
        )
        with self.assertRaises(Http404):
            require_aid_director_access(
                self.subject, school_id=self.other_school.pk,
            )
        event = SchoolGrantDecisionEvent.objects.get()
        self.assertEqual(event.actor_user_id, self.approver.pk)
        self.assertEqual(event.target_user_id, self.subject.pk)
        self.assertEqual(event.action, "CREATED")
        self.assertEqual(event.grant_id, grant.pk)

    def test_explicit_flag_is_disabled_by_default(self):
        self.verify()
        with self.settings(JIREH_FIRST_DIRECTOR_BOOTSTRAP_ENABLED=False):
            with self.assertRaises(PermissionDenied):
                self.propose()
        self.assertFalse(FirstDirectorBootstrapRequest.objects.exists())

    def test_empty_and_single_operator_allowlists_rejected(self):
        self.verify()
        for allowed in ((), (self.proposer.pk,), ("forged",)):
            with self.subTest(allowed=allowed):
                with self.settings(JIREH_BOOTSTRAP_OPERATOR_IDS=allowed):
                    with self.assertRaises(PermissionDenied):
                        self.propose()
        self.assertFalse(FirstDirectorBootstrapRequest.objects.exists())

    def test_unlisted_admin_and_regular_user_cannot_propose_or_approve(self):
        self.verify()
        for actor in (self.third, self.subject):
            with self.assertRaises(PermissionDenied):
                self.propose(operator=actor)
        with self.assertRaises(PermissionDenied):
            self.propose(operator=AnonymousUser())
        proposal = self.propose()
        for actor in (self.third, self.subject):
            with self.assertRaises(PermissionDenied):
                self.approve(proposal, operator=actor)
        self.assertFalse(SchoolStaffAccess.objects.exists())

    def test_wrong_operator_password_prevents_grant(self):
        self.verify()
        with self.assertRaises(PermissionDenied):
            self.propose(operator_password="incorrect")
        proposal = self.propose()
        with self.assertRaises(PermissionDenied):
            self.approve(proposal, operator_password="incorrect")
        self.assertFalse(SchoolStaffAccess.objects.exists())

    def test_failed_password_checks_exhaust_operator_budget(self):
        self.verify()
        for _ in range(10):
            with self.assertRaises(PermissionDenied):
                self.propose(operator_password="invalid")
        self.assertEqual(LoginAttemptBudget.objects.get().attempt_count, 10)
        with self.assertRaises(PermissionDenied):
            self.propose()
        self.assertFalse(FirstDirectorBootstrapRequest.objects.exists())
        self.assertFalse(SchoolStaffAccess.objects.exists())

    def test_rejected_reference_does_not_refund_attempt(self):
        self.verify()
        with self.assertRaises(ValidationError):
            self.propose(authorization_reference="invalid")
        self.assertEqual(LoginAttemptBudget.objects.get().attempt_count, 1)
        self.assertFalse(FirstDirectorBootstrapRequest.objects.exists())

    def test_distinct_operator_budgets_and_storage_outage(self):
        self.verify()
        proposal = self.propose()
        self.approve(proposal)
        self.assertEqual(
            sorted(LoginAttemptBudget.objects.values_list("attempt_count", flat=True)),
            [1, 1],
        )
        with patch(
            "jireh.schools.first_director_bootstrap.charge_bootstrap_operator_attempt",
            side_effect=DatabaseError("synthetic store unavailable"),
        ):
            with self.assertRaises(PermissionDenied):
                self.propose()
        self.assertEqual(LoginAttemptBudget.objects.count(), 2)

    def test_two_people_must_be_distinct_and_not_subject(self):
        self.verify()
        proposal = self.propose()
        with self.assertRaises(PermissionDenied):
            self.approve(proposal, operator=self.proposer)
        with self.assertRaises(Http404):
            self.propose(subject_user_id=self.proposer.pk)
        with self.assertRaises(ValidationError):
            self.propose(subject_user_id=self.other_subject.pk)
        self.assertFalse(SchoolStaffAccess.objects.exists())

    def test_invalid_school_unverified_subject_and_fake_reference(self):
        for ref in ("no", "", " contains spaces", "TOKEN\nNEWLINE", "a" * 121):
            with self.subTest(ref=ref):
                with self.assertRaises(ValidationError):
                    self.propose(authorization_reference=ref)
        with self.assertRaises(ValidationError):
            self.propose()
        self.verify()
        with self.assertRaises(Http404):
            self.propose(school_id=self.school.pk.__class__(int=0))
        self.assertFalse(SchoolStaffAccess.objects.exists())

    def test_approval_reference_mismatch_and_replay_are_blocked(self):
        self.verify()
        proposal = self.propose()
        with self.assertRaises(PermissionDenied):
            self.approve(
                proposal, authorization_reference="SCHOOL-AUTHORIZATION-2026-002",
            )
        self.approve(proposal)
        with self.assertRaises(ValidationError):
            self.approve(proposal)
        with self.assertRaises(ValidationError):
            self.propose()
        self.assertEqual(SchoolStaffAccess.objects.count(), 1)
        self.assertEqual(SchoolGrantDecisionEvent.objects.count(), 1)

    def test_pending_proposal_cannot_be_overwritten(self):
        self.verify()
        self.propose()
        with self.assertRaises(ValidationError):
            self.propose()
        self.assertEqual(FirstDirectorBootstrapRequest.objects.count(), 1)
        self.assertFalse(SchoolStaffAccess.objects.exists())

    def test_expired_proposal_blocks_approval_and_can_be_superseded(self):
        self.verify()
        now = timezone.now()
        with patch(
            "jireh.schools.first_director_bootstrap.timezone.now",
            return_value=now - timedelta(minutes=16),
        ):
            old = self.propose()
        with self.assertRaises(ValidationError):
            self.approve(old)
        new = self.propose()
        old.refresh_from_db()
        self.assertIsNotNone(old.closed_at)
        self.assertNotEqual(new.pk, old.pk)
        self.approve(new)
        self.assertEqual(SchoolStaffAccess.objects.count(), 1)

    def test_subject_deactivation_between_approval_steps_fails_closed(self):
        self.verify()
        proposal = self.propose()
        self.subject.is_active = False
        self.subject.save(update_fields=["is_active"])
        with self.assertRaises(ValidationError):
            self.approve(proposal)
        self.assertFalse(SchoolStaffAccess.objects.exists())

    def test_existing_even_revoked_director_disqualifies_bootstrap(self):
        self.verify()
        first = SchoolStaffAccess.objects.create(
            school=self.school, user=self.subject,
            role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        )
        with self.assertRaises(ValidationError):
            self.propose()
        first.is_active = False
        first.save(update_fields=["is_active", "updated_at"])
        with self.assertRaises(ValidationError):
            self.propose()
        self.assertFalse(FirstDirectorBootstrapRequest.objects.exists())

    def test_audit_failure_rolls_back_both_grant_and_approval(self):
        self.verify()
        proposal = self.propose()
        with patch.object(
            SchoolGrantDecisionEvent.objects, "create",
            side_effect=RuntimeError("Audit unavailable"),
        ):
            with self.assertRaisesMessage(RuntimeError, "Audit unavailable"):
                self.approve(proposal)
        self.assertFalse(SchoolStaffAccess.objects.exists())
        proposal.refresh_from_db()
        self.assertIsNone(proposal.approved_at)
        self.assertIsNone(proposal.grant_id)
        self.assertFalse(SchoolGrantDecisionEvent.objects.exists())

    def test_operator_revocation_before_approval_fails_closed(self):
        self.verify()
        proposal = self.propose()
        self.approver.is_active = False
        self.approver.save(update_fields=["is_active"])
        with self.assertRaises(PermissionDenied):
            self.approve(proposal)
        self.assertFalse(SchoolStaffAccess.objects.exists())

    def test_audit_model_is_append_only(self):
        self.verify()
        proposal = self.propose()
        self.approve(proposal)
        proposal.refresh_from_db()
        proposal.subject = self.other_subject
        with self.assertRaises(ValidationError):
            proposal.save()
        with self.assertRaises(ValidationError):
            proposal.delete()

    def test_postgres_raw_sql_cannot_rewrite_approval(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL immutable authorization evidence.")
        self.verify()
        proposal = self.propose()
        self.approve(proposal)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                FirstDirectorBootstrapRequest.objects.filter(
                    pk=proposal.pk,
                ).update(authorization_reference="FORGED-REF-12345")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                FirstDirectorBootstrapRequest.objects.filter(
                    pk=proposal.pk,
                ).delete()
