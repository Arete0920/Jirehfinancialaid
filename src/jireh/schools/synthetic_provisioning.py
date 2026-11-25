"""Atomic inactive-school provisioning rehearsal, disposable tests only.

Adapt the inactive creation, audit rollback and idempotent replay patterns
from CROWN backend/platform_ops/provisioning.py at
46b56609fe18360299b08eabaa8bccdffb356a0e. Reuse Jireh's own setup receipt,
verified preparation history, and registry-backed action proofs.
No runtime route, live school creation, activation, grants or integrations.
"""

import hashlib
from dataclasses import asdict

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction

from .demo_preparation_jobs import _check_context, _verified_history
from .demo_setup_intents import _candidate_evidence, _locked_setup_operator
from .models import (
    OperatorWebAuthnActionIntent, School, SchoolSetupIntent,
    SyntheticSchoolProvisioningReceipt,
)
from .operator_webauthn_actions import (
    _REFERENCE, _setup_action_digest, _setup_uuid, consume_setup_action_proof,
)
from .school_setup_preflight import (
    SchoolSetupPreflightError, validate_school_setup_candidate,
)


def _candidate(payload):
    try:
        candidate = validate_school_setup_candidate(payload)
    except SchoolSetupPreflightError:
        raise ValidationError("Invalid school setup proposal.") from None
    key, digest = _candidate_evidence(asdict(candidate), privileged=True)
    return candidate, key, digest


def _reference_digest(reference):
    if (type(reference) is not str or not reference.startswith("SYNTHETIC-")
            or not _REFERENCE.fullmatch(reference)):
        raise PermissionDenied("Fictional authorization reference required.")
    return hashlib.sha256(
        b"jireh-synthetic-provisioning-reference-v1\x00" + reference.encode("ascii")
    ).hexdigest()


def _read_exact_replay(existing, *, candidate, setup, preparation, proposer,
                       approver, proposal_id, approval_id, reference, digest):
    """A committed exact request may be read back, never executed twice."""
    proposal, approval = existing.proposal_proof, existing.approval_proof
    school = existing.school
    if (
        existing.preparation_id != preparation.pk
        or existing.reference_digest != digest
        or existing.proposal_proof_id != proposal_id
        or existing.approval_proof_id != approval_id
        or proposal.operator_id != proposer.pk or approval.operator_id != approver.pk
        or proposal.action != OperatorWebAuthnActionIntent.ACTION_SETUP_PROPOSE
        or approval.action != OperatorWebAuthnActionIntent.ACTION_SETUP_APPROVE
        or proposal.consumed_at is None or approval.consumed_at is None
        or school.is_active or school.code != candidate.code
        or school.name != candidate.name or school.timezone != candidate.timezone
    ):
        raise PermissionDenied("Synthetic provisioning replay denied.")
    for proof, actor in ((proposal, proposer), (approval, approver)):
        expected = _setup_action_digest(
            operator_id=actor.pk, action=proof.action, setup_intent_id=setup.pk,
            authorization_reference=reference,
        )
        if proof.payload_digest != expected:
            raise PermissionDenied("Synthetic provisioning replay denied.")
    return existing


def provision_synthetic_inactive_school(
    *, proposer, approver, payload, proposal_proof_id, approval_proof_id,
    authorization_reference,
):
    """Rehearse two-person authorization and inactive creation atomically.

    Only fictional authorization references are accepted. They do not verify
    a real external authorization. The exact receipt is returned on replay
    by currently eligible operators; no second school or audit row is made.
    """
    _check_context(proposer, privileged=True)
    _check_context(approver, privileged=True)
    if proposer.pk is None or approver.pk is None or proposer.pk == approver.pk:
        raise PermissionDenied("Two distinct setup operators required.")
    proposal_id = _setup_uuid(proposal_proof_id)
    approval_id = _setup_uuid(approval_proof_id)
    if proposal_id == approval_id:
        raise PermissionDenied("Distinct setup proofs required.")
    reference_digest = _reference_digest(authorization_reference)
    candidate, key, candidate_digest = _candidate(payload)
    try:
        with transaction.atomic(durable=True):
            # Match the existing operator-then-receipt lock order and acquire
            # both operator rows in a deterministic order for concurrent replay.
            accounts = {
                actor.pk: _locked_setup_operator(actor, privileged=True)
                for actor in sorted((proposer, approver), key=lambda user: user.pk)
            }
            owner, reviewer = accounts[proposer.pk], accounts[approver.pk]
            setup = SchoolSetupIntent.objects.select_for_update().filter(
                idempotency_key=key, proposed_by=owner,
                candidate_digest=candidate_digest,
            ).first()
            if setup is None:
                raise PermissionDenied("Exact owned setup receipt required.")
            history = _verified_history(setup)
            if not history or history[-1].action != "PREPARED":
                raise PermissionDenied("Verified completed preparation required.")
            prepared = history[-1]
            existing = SyntheticSchoolProvisioningReceipt.objects.filter(
                setup=setup,
            ).first()
            if existing is not None:
                return _read_exact_replay(
                    existing, candidate=candidate, setup=setup,
                    preparation=prepared, proposer=owner, approver=reviewer,
                    proposal_id=proposal_id, approval_id=approval_id,
                    reference=authorization_reference, digest=reference_digest,
                )
            if School.objects.filter(code=candidate.code).exists():
                raise PermissionDenied("School code no longer available.")
            for actor, proof_id, action in (
                (owner, proposal_id, OperatorWebAuthnActionIntent.ACTION_SETUP_PROPOSE),
                (reviewer, approval_id, OperatorWebAuthnActionIntent.ACTION_SETUP_APPROVE),
            ):
                consume_setup_action_proof(
                    operator=actor, intent_id=proof_id, action=action,
                    setup_intent_id=setup.pk,
                    authorization_reference=authorization_reference,
                )
            school = School.objects.create(
                code=candidate.code, name=candidate.name, timezone=candidate.timezone,
                is_active=False,
            )
            return SyntheticSchoolProvisioningReceipt.objects.create(
                setup=setup, preparation=prepared, school=school,
                proposal_proof_id=proposal_id, approval_proof_id=approval_id,
                reference_digest=reference_digest,
            )
    except (DatabaseError, RuntimeError, ValidationError):
        # A uniqueness race, invalid model write or audit outage rolls back
        # both proof consumptions and the school row. Never disclose details.
        raise PermissionDenied("Synthetic provisioning could not commit.") from None
