"""End-to-end fictional setup rehearsal using the existing two-key fixture."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, IntegrityError, connections, transaction
from django.http import Http404
from django.test import Client, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse

from .demo_preparation_jobs import advance_synthetic_preparation
from .demo_setup_intents import record_synthetic_setup_intent
from .demo_seed import DEMO_PASSWORD
from .models import (
    AcademicYear, FirstDirectorBootstrapRequest, Household,
    OperatorWebAuthnActionIntent, School, SchoolStaffAccess,
    SyntheticSchoolProvisioningReceipt,
)
from .operator_webauthn_actions import (
    begin_director_action_proof, complete_director_action_proof,
    begin_setup_action_proof, complete_setup_action_proof,
)
from .operator_webauthn_registry import revoke_registered_operator_credential
from .synthetic_provisioning import provision_synthetic_inactive_school
from .synthetic_school_registry import (
    RegistryIntegrityError, read_synthetic_school_registry,
)
from .test_first_director_mfa import FirstDirectorProofFixture, REFERENCE as DIRECTOR_REFERENCE
from .test_onboarding_rehearsal import FictionalOnboardingRehearsal
from .test_operator_webauthn_registry import CREDENTIAL_ID


REFERENCE = "SYNTHETIC-SCHOOL-SETUP-2026"


@override_settings(
    ROOT_URLCONF="jireh.schools.urls",
    JIREH_SYNTHETIC_SETUP_INTENT_ONLY=True,
    JIREH_SYNTHETIC_PREPARATION_JOB_ONLY=True,
    JIREH_SYNTHETIC_PROVISIONING_ONLY=True,
    JIREH_SCHOOL_SETUP_ACTION_MFA_ENABLED=True,
)
class SyntheticProvisioningTests(
    FirstDirectorProofFixture, FictionalOnboardingRehearsal, TransactionTestCase,
):
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


    def test_registry_reads_only_operator_linked_receipts_and_no_private_fields(self):
        self.assertEqual(read_synthetic_school_registry(operator=self.operator), ())
        self.prepare()
        receipt = self.execute(self.proofs())
        first = read_synthetic_school_registry(operator=self.operator)
        self.assertEqual(first, read_synthetic_school_registry(operator=self.second))
        self.assertEqual(len(first), 1)
        row = first[0]
        self.assertEqual(row.school_id, receipt.school_id)
        self.assertEqual(row.director_status, "SCHOOL_INACTIVE")
        self.assertFalse(row.is_active)
        self.assertEqual(row.active_director_count, 0)
        self.assertEqual(row.academic_year_count, 0)
        other = get_user_model().objects.create_superuser(
            username="synthetic-unrelated-registry-operator",
            email="unrelated@example.invalid", password=DEMO_PASSWORD,
        )
        with self.assertRaises(PermissionDenied):
            read_synthetic_school_registry(operator=other)
        with self.settings(JIREH_BOOTSTRAP_OPERATOR_IDS=(
            self.operator.pk, self.second.pk, other.pk,
        )):
            self.assertEqual(read_synthetic_school_registry(operator=other), ())
        client = Client()
        url = reverse("jireh_test_school_registry")
        self.assertEqual(client.get(url).status_code, 403)
        client.force_login(self.operator)
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        result = response.json()["schools"]
        self.assertEqual(result, [{
            "school_id": str(receipt.school_id), "code": self.payload["code"],
            "name": self.payload["name"], "timezone": self.payload["timezone"],
            "is_active": False, "academic_year_count": 0,
            "director_status": "SCHOOL_INACTIVE", "active_director_count": 0,
        }])
        self.assertEqual(client.get(url, {"school_id": str(receipt.school_id)}).status_code, 400)
        self.assertEqual(client.post(url).status_code, 405)
        with self.settings(JIREH_SYNTHETIC_PROVISIONING_ONLY=False):
            self.assertEqual(client.get(url).status_code, 403)
        with self.settings(ROOT_URLCONF="jireh.runtime.urls"):
            self.assertEqual(client.get(url).status_code, 404)

    def test_registry_fails_closed_on_inconsistent_school_or_history(self):
        self.prepare()
        receipt = self.execute(self.proofs())
        with patch(
            "jireh.schools.synthetic_school_registry._verified_history", return_value=[],
        ):
            with self.assertRaises(RegistryIntegrityError):
                read_synthetic_school_registry(operator=self.operator)
        School.objects.filter(pk=receipt.school_id).update(name="Synthetic Changed Name")
        with self.assertRaises(RegistryIntegrityError):
            read_synthetic_school_registry(operator=self.operator)
        client = Client()
        client.force_login(self.operator)
        response = client.get(reverse("jireh_test_school_registry"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "School registry unavailable."})

    def _fresh_director_proof(self, *, actor, action, **scope):
        # Setup already spent the first authenticator counter. A director
        # action needs an independent assertion and a strictly higher count.
        first = actor.pk == self.operator.pk
        options, proof = begin_director_action_proof(
            operator=actor,
            credential_id_digest=self.digest if first else self.second_digest,
            action=action, authorization_reference=DIRECTOR_REFERENCE, **scope,
        )
        self.assertEqual(complete_director_action_proof(
            operator=actor, intent_id=proof,
            response=self.signed(
                options, key=self.key if first else self.second_key,
                credential_id=CREDENTIAL_ID if first else self.second_key_id,
                count=2,
            ),
        ), 2)
        return proof

    def test_provisioned_school_through_independent_director_and_family_onboarding(self):
        self.prepare()
        setup_proofs = self.proofs()
        receipt = self.execute(setup_proofs)
        self.school = receipt.school
        users = get_user_model()
        self.subject = users.objects.create_user(
            username="synthetic-new-school-director", password=DEMO_PASSWORD,
        )
        self.verify_director_mailbox()
        with self.settings(JIREH_FIRST_DIRECTOR_BOOTSTRAP_ENABLED=True):
            with self.assertRaises(Http404):
                self.propose(mfa_intent_id=setup_proofs[0])
            self.assertFalse(FirstDirectorBootstrapRequest.objects.exists())
            self.assertFalse(SchoolStaffAccess.objects.exists())
            self.assertEqual(
                read_synthetic_school_registry(operator=self.operator)[0].director_status,
                "SCHOOL_INACTIVE",
            )

            # Deliberate fixture transition, NOT a callable activation service.
            # Live activation requires separate authorization and is out of scope.
            self.school.is_active = True
            self.school.save(update_fields=["is_active", "updated_at"])
            AcademicYear.objects.create(
                school=self.school, name="2026-27",
                start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
            )
            row = read_synthetic_school_registry(operator=self.operator)[0]
            self.assertEqual((row.academic_year_count, row.director_status),
                             (1, "DIRECTOR_NOT_ASSIGNED"))
            with self.assertRaises(PermissionDenied):
                self.propose(mfa_intent_id=setup_proofs[0])

            proposal_proof = self._fresh_director_proof(
                actor=self.operator,
                action=OperatorWebAuthnActionIntent.ACTION_DIRECTOR_PROPOSE,
                school_id=self.school.pk, subject_user_id=self.subject.pk,
            )
            request = self.propose(mfa_intent_id=proposal_proof)
            self.assertEqual(
                read_synthetic_school_registry(operator=self.second)[0].director_status,
                "DIRECTOR_APPROVAL_PENDING",
            )
            self.assertFalse(SchoolStaffAccess.objects.exists())
            approval_proof = self._fresh_director_proof(
                actor=self.second,
                action=OperatorWebAuthnActionIntent.ACTION_DIRECTOR_APPROVE,
                request_id=request.pk,
            )
            grant = self.approve(request, mfa_intent_id=approval_proof)
            self.assertEqual(grant.school_id, self.school.pk)
            row = read_synthetic_school_registry(operator=self.operator)[0]
            self.assertEqual((row.director_status, row.active_director_count),
                             ("DIRECTOR_ACCESS_AVAILABLE", 1))
            self.assertEqual(OperatorWebAuthnActionIntent.objects.filter(
                consumed_at__isnull=False,
            ).count(), 4)

        # Reuse the existing full local-mail invitation, CSRF, cross-school
        # denial, redemption and revocation rehearsal on the provisioned school.
        other = School.objects.create(
            code="synthetic-onboarding-control", name="Synthetic Control School",
        )
        other_director = users.objects.create_user(
            username="synthetic-onboarding-control-director", password=DEMO_PASSWORD,
        )
        SchoolStaffAccess.objects.create(
            school=other, user=other_director, role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        )
        family = users.objects.create_user(
            username="synthetic-new-school-family", password=DEMO_PASSWORD,
        )
        household = Household.objects.create(school=self.school, name="Fictional Family")
        other_household = Household.objects.create(school=other, name="Fictional Control Family")
        demo = {
            "school_a": self.school, "school_b": other,
            "household_a": household, "household_b": other_household,
            "director_a": self.subject, "director_b": other_director, "parent": family,
        }
        self.rehearse_household_onboarding(demo)
        self.assertEqual(len(read_synthetic_school_registry(operator=self.operator)), 1)
        users.objects.filter(pk=self.subject.pk).update(is_active=False)
        row = read_synthetic_school_registry(operator=self.operator)[0]
        self.assertEqual((row.director_status, row.active_director_count),
                         ("DIRECTOR_ACCESS_UNAVAILABLE", 0))
