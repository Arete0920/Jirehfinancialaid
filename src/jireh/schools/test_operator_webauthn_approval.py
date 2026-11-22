"""Synthetic independent owner/integration-manager enrollment approval tests."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from .models import (
    LoginAttemptBudget, OperatorWebAuthnCredential,
    OperatorWebAuthnEnrollmentApproval, OperatorWebAuthnPossessionChallenge,
)
from .operator_webauthn_approval import approve_pending_operator_credential
from .test_operator_webauthn_possession import PendingWebAuthnPossessionTests


PASSWORD = "Synthetic-Only-Possession-Operator-2026!"
REFERENCE = "IDENTITY-VERIFIED-REF-2026-0001"


class OperatorEnrollmentApprovalTests(TransactionTestCase):
    # Reuse the established synthetic registration + cryptographic proof fixture
    # without inheriting and rerunning the prior test class's test methods.
    proof_api = PendingWebAuthnPossessionTests.proof_api
    begin = PendingWebAuthnPossessionTests.begin
    complete = PendingWebAuthnPossessionTests.complete
    assertion = PendingWebAuthnPossessionTests.assertion

    def setUp(self):
        PendingWebAuthnPossessionTests.setUp(self)
        self.manager = get_user_model().objects.create_superuser(
            username="credential-integration-manager",
            email="manager@example.invalid",
            password=PASSWORD,
        )
        context = self.settings(
            JIREH_OPERATOR_ENROLLMENT_APPROVAL_ENABLED=True,
            JIREH_ENROLLMENT_OWNER_USER_ID=self.other.pk,
            JIREH_ENROLLMENT_MANAGER_USER_ID=self.manager.pk,
        )
        context.enable()
        self.addCleanup(context.disable)

    def prove(self):
        options, proof_id = self.begin()
        self.assertEqual(
            self.complete(proof_id, self.assertion(options)), self.digest,
        )
        return proof_id

    def approve(self, **overrides):
        values = dict(
            approver=self.other,
            approver_password=PASSWORD,
            operator_id=self.operator.pk,
            credential_id_digest=self.digest,
            identity_verification_reference=REFERENCE,
        )
        values.update(overrides)
        return approve_pending_operator_credential(**values)

    def test_owner_approves_proven_credential_once_with_immutable_evidence(self):
        proof_id = self.prove()
        self.assertFalse(connection.in_atomic_block)
        approval = self.approve()
        credential = OperatorWebAuthnCredential.objects.get(
            credential_id_digest=self.digest,
        )
        self.assertIsNotNone(credential.enrollment_verified_at)
        self.assertEqual(approval.possession_proof_id, proof_id)
        self.assertEqual(approval.approver_role, "OWNER")
        self.assertEqual(approval.approver_id, self.other.pk)
        self.assertEqual(approval.operator_id, self.operator.pk)
        self.assertEqual(
            approval.identity_verification_reference, REFERENCE,
        )
        with self.assertRaises(PermissionDenied):
            self.approve()
        self.assertEqual(OperatorWebAuthnEnrollmentApproval.objects.count(), 1)
        with self.assertRaises(ValidationError):
            approval.delete()
        approval.identity_verification_reference = "ALTERED-REFERENCE-2026"
        with self.assertRaises(ValidationError):
            approval.save()
        self.assertFalse(connection.in_atomic_block)

    def test_integration_manager_has_same_explicit_approval_authority(self):
        self.prove()
        approval = self.approve(approver=self.manager)
        self.assertEqual(approval.approver_role, "INTEGRATION_MANAGER")
        self.assertEqual(approval.approver_id, self.manager.pk)

    def test_self_approval_and_unlisted_privileged_actors_are_rejected(self):
        self.prove()
        with self.settings(
            JIREH_ENROLLMENT_OWNER_USER_ID=self.operator.pk,
            JIREH_ENROLLMENT_MANAGER_USER_ID=self.manager.pk,
        ):
            with self.assertRaises(PermissionDenied):
                self.approve(approver=self.operator)
        outside = get_user_model().objects.create_superuser(
            username="not-authorized-enrollment-approver",
            email="outsider@example.invalid",
            password=PASSWORD,
        )
        with self.assertRaises(PermissionDenied):
            self.approve(approver=outside)
        self.assertFalse(OperatorWebAuthnEnrollmentApproval.objects.exists())

    def test_flag_and_ambiguous_authority_configuration_fail_closed(self):
        self.prove()
        with self.settings(JIREH_OPERATOR_ENROLLMENT_APPROVAL_ENABLED=False):
            with self.assertRaises(PermissionDenied):
                self.approve()
        with self.settings(
            JIREH_ENROLLMENT_OWNER_USER_ID=self.other.pk,
            JIREH_ENROLLMENT_MANAGER_USER_ID=self.other.pk,
        ):
            with self.assertRaises(PermissionDenied):
                self.approve()
        self.assertFalse(OperatorWebAuthnEnrollmentApproval.objects.exists())

    def test_fresh_proof_and_external_identity_evidence_required(self):
        with self.assertRaises(PermissionDenied):
            self.approve()
        self.prove()
        for reference in ("", "not verified", "A" * 121):
            with self.subTest(reference=reference):
                with self.assertRaises(PermissionDenied):
                    self.approve(identity_verification_reference=reference)
        self.assertFalse(OperatorWebAuthnEnrollmentApproval.objects.exists())
        proof = OperatorWebAuthnPossessionChallenge.objects.get(
            verified_at__isnull=False,
        )
        # Keep immutable proof evidence intact; advance the approval clock
        # instead to exercise expiry on SQLite and PostgreSQL alike.
        self.assertIsNotNone(proof.verified_at)
        with patch(
            "jireh.schools.operator_webauthn_approval.timezone.now",
            return_value=timezone.now() + timedelta(hours=25),
        ):
            with self.assertRaises(PermissionDenied):
                self.approve()

    def test_wrong_password_consumes_rate_budget_and_does_not_activate(self):
        self.prove()
        with self.assertRaises(PermissionDenied):
            self.approve(approver_password="wrong-password")
        self.assertEqual(LoginAttemptBudget.objects.get().attempt_count, 1)
        self.assertIsNone(
            OperatorWebAuthnCredential.objects.get(
                credential_id_digest=self.digest,
            ).enrollment_verified_at
        )

    def test_revoked_key_cannot_be_approved(self):
        self.prove()
        OperatorWebAuthnCredential.objects.filter(
            credential_id_digest=self.digest,
        ).update(revoked_at=timezone.now())
        with self.assertRaises(PermissionDenied):
            self.approve()
        self.assertFalse(OperatorWebAuthnEnrollmentApproval.objects.exists())

    def test_db_failure_rolls_back_both_activation_and_evidence(self):
        self.prove()
        with patch(
            "jireh.schools.operator_webauthn_approval.OperatorWebAuthnCredential.save",
            side_effect=DatabaseError("synthetic activation failure"),
        ):
            with self.assertRaises(PermissionDenied):
                self.approve()
        self.assertFalse(OperatorWebAuthnEnrollmentApproval.objects.exists())
        self.assertIsNone(
            OperatorWebAuthnCredential.objects.get(
                credential_id_digest=self.digest,
            ).enrollment_verified_at
        )

    def test_outer_transaction_and_raw_sql_audit_mutation_fail(self):
        self.prove()
        with transaction.atomic():
            with self.assertRaises(PermissionDenied):
                self.approve()
        approval = self.approve()
        if connection.vendor != "postgresql":
            return
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OperatorWebAuthnEnrollmentApproval.objects.filter(
                    pk=approval.pk,
                ).update(identity_verification_reference="FORGED-REF-2026")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OperatorWebAuthnEnrollmentApproval.objects.filter(
                    pk=approval.pk,
                ).delete()
