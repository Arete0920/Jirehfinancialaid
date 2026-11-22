"""Synthetic cryptographic contracts for action-specific WebAuthn MFA evidence."""

from unittest.mock import patch
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import ec
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from .models import OperatorWebAuthnActionIntent
from .operator_webauthn_actions import (
    begin_director_action_proof,
    complete_director_action_proof,
    consume_director_action_proof,
    director_action_digest,
)
from .operator_webauthn_registry import revoke_registered_operator_credential
from .test_operator_webauthn_registry import OperatorCredentialRegistryTests


REFERENCE = "SCHOOL-AUTHORIZATION-2026-001"


class OperatorActionWebAuthnTests(TransactionTestCase):
    assertion = OperatorCredentialRegistryTests.assertion

    def setUp(self):
        OperatorCredentialRegistryTests.setUp(self)
        self.school_id = uuid4()
        self.subject_id = uuid4()
        self.request_id = uuid4()
        self.context = self.settings(JIREH_OPERATOR_ACTION_MFA_ENABLED=True)
        self.context.enable()
        self.addCleanup(self.context.disable)

    def proposal(self, **override):
        scope = dict(
            action=OperatorWebAuthnActionIntent.ACTION_DIRECTOR_PROPOSE,
            authorization_reference=REFERENCE,
            school_id=self.school_id,
            subject_user_id=self.subject_id,
        )
        scope.update(override)
        return scope

    def approval(self, **override):
        scope = dict(
            action=OperatorWebAuthnActionIntent.ACTION_DIRECTOR_APPROVE,
            authorization_reference=REFERENCE,
            request_id=self.request_id,
        )
        scope.update(override)
        return scope

    def begin(self, scope=None):
        return begin_director_action_proof(
            operator=self.operator,
            credential_id_digest=self.digest,
            **(self.proposal() if scope is None else scope),
        )

    def complete(self, intent_id, options, **kwargs):
        return complete_director_action_proof(
            operator=self.operator, intent_id=intent_id,
            response=self.assertion(options, **kwargs),
        )

    def consume(self, intent_id, scope=None, operator=None):
        return consume_director_action_proof(
            operator=self.operator if operator is None else operator,
            intent_id=intent_id,
            **(self.proposal() if scope is None else scope),
        )

    def test_valid_action_proof_consumed_once_inside_grant_transaction(self):
        options, intent_id = self.begin()
        self.assertEqual(self.complete(intent_id, options), 1)
        with transaction.atomic():
            self.assertEqual(self.consume(intent_id), intent_id)
        row = OperatorWebAuthnActionIntent.objects.get(pk=intent_id)
        self.assertIsNotNone(row.consumed_at)
        with self.assertRaises(PermissionDenied):
            with transaction.atomic():
                self.consume(intent_id)

    def test_approval_scope_is_not_proposal_scope(self):
        scope = self.approval()
        options, intent_id = self.begin(scope)
        self.complete(intent_id, options)
        with self.assertRaises(PermissionDenied):
            with transaction.atomic():
                self.consume(intent_id)
        with transaction.atomic():
            self.assertEqual(self.consume(intent_id, scope), intent_id)

    def test_payload_mismatch_cannot_consume_verified_key(self):
        options, intent_id = self.begin()
        self.complete(intent_id, options)
        for mismatch in (
            self.proposal(subject_user_id=uuid4()),
            self.proposal(school_id=uuid4()),
            self.proposal(authorization_reference="SCHOOL-AUTHORIZATION-2026-002"),
        ):
            with self.subTest(mismatch=mismatch):
                with self.assertRaises(PermissionDenied):
                    with transaction.atomic():
                        self.consume(intent_id, mismatch)
        self.assertIsNone(
            OperatorWebAuthnActionIntent.objects.get(pk=intent_id).consumed_at
        )

    def test_preverified_assertion_is_not_a_forged_action_intent(self):
        with self.assertRaises(PermissionDenied):
            with transaction.atomic():
                self.consume(uuid4())
        self.assertFalse(OperatorWebAuthnActionIntent.objects.exists())

    def test_invalid_signature_cannot_authorize_a_director_action(self):
        options, intent_id = self.begin()
        attacker = ec.generate_private_key(ec.SECP256R1())
        with self.assertRaises(PermissionDenied):
            self.complete(intent_id, options, key=attacker)
        with self.assertRaises(PermissionDenied):
            with transaction.atomic():
                self.consume(intent_id)
        with self.assertRaises(PermissionDenied):
            self.complete(intent_id, options)
        self.assertIsNone(
            OperatorWebAuthnActionIntent.objects.get(pk=intent_id).consumed_at
        )

    def test_different_operator_cannot_complete_or_consume(self):
        options, intent_id = self.begin()
        with self.assertRaises(PermissionDenied):
            complete_director_action_proof(
                operator=self.second, intent_id=intent_id,
                response=self.assertion(options),
            )
        self.complete(intent_id, options)
        with self.assertRaises(PermissionDenied):
            with transaction.atomic():
                self.consume(intent_id, operator=self.second)
        with transaction.atomic():
            self.consume(intent_id)

    def test_revocation_between_signature_and_action_fails(self):
        options, intent_id = self.begin()
        self.complete(intent_id, options)
        revoke_registered_operator_credential(
            operator=self.operator, credential_id_digest=self.digest,
        )
        with self.assertRaises(PermissionDenied):
            with transaction.atomic():
                self.consume(intent_id)

    def test_disabled_flag_cannot_be_bypassed(self):
        with self.settings(JIREH_OPERATOR_ACTION_MFA_ENABLED=False):
            with self.assertRaises(PermissionDenied):
                self.begin()
        self.assertFalse(OperatorWebAuthnActionIntent.objects.exists())

    def test_expired_proof_and_outside_transaction_are_denied(self):
        options, intent_id = self.begin()
        self.complete(intent_id, options)
        with self.assertRaises(PermissionDenied):
            self.consume(intent_id)
        intent = OperatorWebAuthnActionIntent.objects.get(pk=intent_id)
        with patch("jireh.schools.operator_webauthn_actions.timezone.now",
                   return_value=intent.expires_at):
            with self.assertRaises(PermissionDenied):
                with transaction.atomic():
                    self.consume(intent_id)

    def test_grant_transaction_rollback_preserves_one_use_evidence(self):
        options, intent_id = self.begin()
        self.complete(intent_id, options)
        with self.assertRaisesMessage(RuntimeError, "synthetic grant rollback"):
            with transaction.atomic():
                self.consume(intent_id)
                raise RuntimeError("synthetic grant rollback")
        self.assertIsNone(
            OperatorWebAuthnActionIntent.objects.get(pk=intent_id).consumed_at
        )
        with transaction.atomic():
            self.consume(intent_id)

    def test_postgres_raw_rebind_delete_and_reopen_blocked(self):
        if connection.vendor != "postgresql":
            return
        options, intent_id = self.begin()
        self.complete(intent_id, options)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OperatorWebAuthnActionIntent.objects.filter(
                    pk=intent_id,
                ).update(payload_digest="a" * 64)
        with transaction.atomic():
            self.consume(intent_id)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OperatorWebAuthnActionIntent.objects.filter(
                    pk=intent_id,
                ).update(consumed_at=None)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OperatorWebAuthnActionIntent.objects.filter(
                    pk=intent_id,
                ).delete()

    def test_integer_django_subject_ids_bind_to_exact_action(self):
        first = self.proposal(subject_user_id=17)
        second = self.proposal(subject_user_id=18)
        self.assertNotEqual(
            director_action_digest(**first), director_action_digest(**second),
        )
        with self.assertRaises(PermissionDenied):
            director_action_digest(**self.proposal(subject_user_id=True))

    def test_invalid_scope_rejected_before_issuing_credential_challenge(self):
        for scope in (
            self.proposal(request_id=uuid4()),
            self.approval(school_id=self.school_id),
            self.proposal(authorization_reference="unsafe reference"),
        ):
            with self.assertRaises(PermissionDenied):
                self.begin(scope)
        self.assertFalse(OperatorWebAuthnActionIntent.objects.exists())
        self.assertNotEqual(
            director_action_digest(**self.proposal()),
            director_action_digest(**self.approval()),
        )
