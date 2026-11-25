"""End-to-end fictional setup rehearsal using the existing two-key fixture."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, IntegrityError, connections, transaction
from django.test import TransactionTestCase, override_settings, skipUnlessDBFeature

from .demo_preparation_jobs import advance_synthetic_preparation
from .demo_setup_intents import record_synthetic_setup_intent
from .models import (
    AcademicYear, OperatorWebAuthnActionIntent, School, SchoolStaffAccess,
    SyntheticSchoolProvisioningReceipt,
)
from .operator_webauthn_actions import (
    begin_setup_action_proof, complete_setup_action_proof,
)
from .operator_webauthn_registry import revoke_registered_operator_credential
from .synthetic_provisioning import provision_synthetic_inactive_school
from .test_first_director_mfa import FirstDirectorProofFixture
from .test_operator_webauthn_registry import CREDENTIAL_ID


REFERENCE = "SYNTHETIC-SCHOOL-SETUP-2026"


@override_settings(
    ROOT_URLCONF="jireh.schools.urls",
    JIREH_SYNTHETIC_SETUP_INTENT_ONLY=True,
    JIREH_SYNTHETIC_PREPARATION_JOB_ONLY=True,
    JIREH_SYNTHETIC_PROVISIONING_ONLY=True,
    JIREH_SCHOOL_SETUP_ACTION_MFA_ENABLED=True,
)
class SyntheticProvisioningTests(FirstDirectorProofFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        guard = self.settings(JIREH_FIRST_DIRECTOR_BOOTSTRAP_ENABLED=False)
        guard.enable()
        self.addCleanup(guard.disable)
        self.payload = {
            "code": "synthetic-provisioning-academy",
            "name": "Synthetic Provisioning Academy",
            "timezone": "America/New_York",
            "idempotency_key": str(uuid4()),
        }
        self.setup = record_synthetic_setup_intent(
            operator=self.operator, payload=self.payload, privileged=True,
        )

    def prepare(self):
        for command in ("QUEUE", "RUN"):
            result = advance_synthetic_preparation(
                operator=self.operator, payload=self.payload,
                command=command, request_key=uuid4(), privileged=True,
            )
        self.assertEqual(result.action, "PREPARED")
        return result

    def setup_proof(self, *, actor, action, reference=REFERENCE):
        first = actor.pk == self.operator.pk
        options, proof = begin_setup_action_proof(
            operator=actor,
            credential_id_digest=self.digest if first else self.second_digest,
            action=action, setup_intent_id=self.setup.pk,
            authorization_reference=reference,
        )
        self.assertEqual(complete_setup_action_proof(
            operator=actor, intent_id=proof,
            response=self.signed(
                options, key=self.key if first else self.second_key,
                credential_id=CREDENTIAL_ID if first else self.second_key_id,
            ),
        ), 1)
        return proof

    def proofs(self, approval_reference=REFERENCE):
        return (
            self.setup_proof(
                actor=self.operator,
                action=OperatorWebAuthnActionIntent.ACTION_SETUP_PROPOSE,
            ),
            self.setup_proof(
                actor=self.second,
                action=OperatorWebAuthnActionIntent.ACTION_SETUP_APPROVE,
                reference=approval_reference,
            ),
        )

    def execute(self, proofs, **changes):
        args = dict(
            proposer=self.operator, approver=self.second, payload=self.payload,
            proposal_proof_id=proofs[0], approval_proof_id=proofs[1],
            authorization_reference=REFERENCE,
        )
        args.update(changes)
        return provision_synthetic_inactive_school(**args)

    def assert_uncommitted(self):
        self.assertFalse(School.objects.exists())
        self.assertFalse(SyntheticSchoolProvisioningReceipt.objects.exists())
        self.assertFalse(OperatorWebAuthnActionIntent.objects.filter(
            consumed_at__isnull=False,
        ).exists())

    def test_complete_chain_creates_one_inactive_school_and_exact_replay(self):
        prepared = self.prepare()
        proofs = self.proofs()
        result = self.execute(proofs)
        self.assertEqual(result.setup_id, self.setup.pk)
        self.assertEqual(result.preparation_id, prepared.pk)
        self.assertEqual(result.school.code, self.payload["code"])
        self.assertEqual(result.school.name, self.payload["name"])
        self.assertEqual(result.school.timezone, self.payload["timezone"])
        self.assertFalse(result.school.is_active)
        self.assertEqual(self.execute(proofs).pk, result.pk)
        self.assertEqual(School.objects.count(), 1)
        self.assertEqual(SyntheticSchoolProvisioningReceipt.objects.count(), 1)
        self.assertEqual(OperatorWebAuthnActionIntent.objects.filter(
            consumed_at__isnull=False,
        ).count(), 2)
        self.assertFalse(AcademicYear.objects.exists())
        self.assertFalse(SchoolStaffAccess.objects.exists())
        for changes in (
            {"approval_proof_id": uuid4()},
            {"authorization_reference": "SYNTHETIC-OTHER-REFERENCE"},
            {"payload": {**self.payload, "name": "Synthetic Changed Academy"}},
        ):
            with self.subTest(changes=changes), self.assertRaises(PermissionDenied):
                self.execute(proofs, **changes)
        self.assertEqual(School.objects.count(), 1)

    def test_unprepared_wrong_actor_disabled_and_nonfictional_contexts_denied(self):
        proofs = self.proofs()
        with self.assertRaises(PermissionDenied):
            self.execute(proofs)
        self.prepare()
        for changes in (
            {"approver": self.operator},
            {"approval_proof_id": proofs[0]},
            {"authorization_reference": "REAL-SCHOOL-SETUP-2026"},
        ):
            with self.subTest(changes=changes), self.assertRaises(PermissionDenied):
                self.execute(proofs, **changes)
        with self.settings(JIREH_SYNTHETIC_PROVISIONING_ONLY=False):
            with self.assertRaises(PermissionDenied):
                self.execute(proofs)
        with self.settings(ROOT_URLCONF="jireh.runtime.urls"):
            with self.assertRaises(PermissionDenied):
                self.execute(proofs)
        with self.assertRaises(PermissionDenied):
            record_synthetic_setup_intent(
                operator=self.operator, payload=self.payload,
            )
        with self.assertRaises(ValidationError):
            record_synthetic_setup_intent(
                operator=self.operator, privileged=True,
                payload={**self.payload, "code": "nonfictional-academy"},
            )
        self.assert_uncommitted()

    def test_changed_approval_reference_rolls_back_first_proof(self):
        self.prepare()
        proofs = self.proofs(approval_reference="SYNTHETIC-OTHER-REFERENCE")
        with self.assertRaises(PermissionDenied):
            self.execute(proofs)
        self.assert_uncommitted()

    def test_code_conflict_after_preparation_does_not_consume_proofs(self):
        self.prepare()
        proofs = self.proofs()
        conflict = School.objects.create(
            code=self.payload["code"], name="Synthetic Conflict", is_active=False,
        )
        with self.assertRaises(PermissionDenied):
            self.execute(proofs)
        self.assertEqual(School.objects.count(), 1)
        self.assertFalse(SyntheticSchoolProvisioningReceipt.objects.exists())
        self.assertFalse(OperatorWebAuthnActionIntent.objects.filter(
            consumed_at__isnull=False,
        ).exists())
        conflict.delete()
        self.assertFalse(self.execute(proofs).school.is_active)

    def test_audit_failure_rolls_back_school_and_both_proofs(self):
        self.prepare()
        proofs = self.proofs()
        with patch.object(
            SyntheticSchoolProvisioningReceipt.objects, "create",
            side_effect=DatabaseError("fictional audit outage"),
        ):
            with self.assertRaises(PermissionDenied):
                self.execute(proofs)
        self.assert_uncommitted()
        self.assertFalse(self.execute(proofs).school.is_active)

    def test_revoked_approval_credential_rolls_back_first_proof(self):
        self.prepare()
        proofs = self.proofs()
        revoke_registered_operator_credential(
            operator=self.second, credential_id_digest=self.second_digest,
        )
        with self.assertRaises(PermissionDenied):
            self.execute(proofs)
        self.assert_uncommitted()

    @skipUnlessDBFeature("has_select_for_update")
    def test_postgresql_parallel_exact_replay_commits_once(self):
        self.prepare()
        proofs = self.proofs()
        barrier = Barrier(2)

        def run():
            try:
                user_model = get_user_model()
                owner = user_model.objects.get(pk=self.operator.pk)
                reviewer = user_model.objects.get(pk=self.second.pk)
                barrier.wait(timeout=10)
                return self.execute(proofs, proposer=owner, approver=reviewer).pk
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.submit(run), pool.submit(run)
            self.assertEqual(first.result(timeout=25), second.result(timeout=25))
        self.assertEqual(School.objects.count(), 1)
        self.assertEqual(SyntheticSchoolProvisioningReceipt.objects.count(), 1)

    @skipUnlessDBFeature("has_select_for_update")
    def test_postgresql_receipt_is_immutable_and_wrong_links_are_denied(self):
        self.prepare()
        proofs = self.proofs()
        result = self.execute(proofs)
        query = SyntheticSchoolProvisioningReceipt.objects.filter(pk=result.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            query.update(reference_digest="f" * 64)
        with self.assertRaises(IntegrityError), transaction.atomic():
            query.delete()
        self.assertEqual(query.get().school_id, result.school_id)
