"""Disabled internal owner/integration-manager credential identity approval.

Approval requires independent identity-check attestation, a successful recent
WebAuthn proof for an unverified credential, and owner/manager password
reauthentication. This is NOT an operator session, public API, or permission
to use first-director bootstrap. The external identity evidence must be
independently checked by the named human; its reference is not self-validating.
"""

import re
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, transaction
from django.utils import timezone

from .login_budget import charge_bootstrap_operator_attempt
from .models import (
    OperatorWebAuthnCredential,
    OperatorWebAuthnEnrollmentApproval,
    OperatorWebAuthnPossessionChallenge,
    OperatorWebAuthnRegistration,
)


REFERENCE = re.compile(r"\A[A-Z0-9][A-Z0-9-]{11,119}\Z")
PROOF_MAX_AGE = timedelta(hours=24)


def _approval_configuration():
    if getattr(settings, "JIREH_OPERATOR_ENROLLMENT_APPROVAL_ENABLED", False) is not True:
        raise PermissionDenied("Operator enrollment approval disabled.")
    owner = getattr(settings, "JIREH_ENROLLMENT_OWNER_USER_ID", None)
    manager = getattr(settings, "JIREH_ENROLLMENT_MANAGER_USER_ID", None)
    # Distinct configured privileged identities; no implicit fallback.
    if (type(owner) is not int or type(manager) is not int
            or owner <= 0 or manager <= 0 or owner == manager):
        raise PermissionDenied("Independent approval authorities not configured.")
    return {owner: OperatorWebAuthnEnrollmentApproval.ROLE_OWNER,
            manager: OperatorWebAuthnEnrollmentApproval.ROLE_INTEGRATION_MANAGER}


def _approver_identity(approver, authority):
    pk = getattr(approver, "pk", None)
    if (not getattr(approver, "is_authenticated", False)
            or pk not in authority):
        raise PermissionDenied("Approved owner or integration manager required.")
    account = (
        get_user_model()._default_manager.select_for_update()
        .filter(pk=pk, is_active=True, is_staff=True, is_superuser=True)
        .first()
    )
    if account is None:
        raise PermissionDenied("Approved owner or integration manager required.")
    return account


def approve_pending_operator_credential(
    *, approver, approver_password, operator_id, credential_id_digest,
    identity_verification_reference,
):
    """Activate exactly one pending key; never auto-verify identity.

    A human owner/integration manager must independently verify the person
    and institutional authorization corresponding to the bounded reference.
    Reauthentication attempts are charged before the mutation transaction.
    """
    authority = _approval_configuration()
    if getattr(approver, "pk", None) not in authority:
        raise PermissionDenied("Approved owner or integration manager required.")
    try:
        with transaction.atomic(durable=True):
            allowed, _ = charge_bootstrap_operator_attempt(operator_id=approver.pk)
    except (DatabaseError, RuntimeError):
        raise PermissionDenied("Approval attempt controls unavailable.") from None
    if not allowed:
        raise PermissionDenied("Approval attempt limit exceeded.")
    if (not isinstance(approver_password, str)
            or not 1 <= len(approver_password) <= 1024
            or not isinstance(identity_verification_reference, str)
            or not REFERENCE.fullmatch(identity_verification_reference)
            or not isinstance(credential_id_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", credential_id_digest)):
        raise PermissionDenied("Approval credentials or evidence invalid.")

    try:
        with transaction.atomic(durable=True):
            authority = _approval_configuration()
            actor = _approver_identity(approver, authority)
            if not actor.check_password(approver_password):
                raise PermissionDenied("Approver authentication failed.")
            if type(operator_id) is not int or operator_id <= 0 or actor.pk == operator_id:
                raise PermissionDenied("Independent operator approval required.")
            operator = (
                get_user_model()._default_manager.select_for_update()
                .filter(pk=operator_id, is_active=True, is_staff=True,
                        is_superuser=True).first()
            )
            if operator is None:
                raise PermissionDenied("Eligible operator required.")
            credential = (
                OperatorWebAuthnCredential.objects.select_for_update()
                .filter(
                    operator=operator, credential_id_digest=credential_id_digest,
                    enrollment_verified_at__isnull=True,
                    revoked_at__isnull=True,
                ).first()
            )
            if credential is None:
                raise PermissionDenied("Pending credential required.")
            registration = (
                OperatorWebAuthnRegistration.objects.select_for_update()
                .filter(
                    operator=operator, credential_id_digest=credential_id_digest,
                    closed_at__isnull=False,
                ).order_by("-closed_at").first()
            )
            now = timezone.now()
            if registration is None or registration.closed_at > registration.expires_at:
                raise PermissionDenied("Completed registration proof required.")
            proof = (
                OperatorWebAuthnPossessionChallenge.objects.select_for_update()
                .filter(
                    operator=operator, credential=credential,
                    verified_at__isnull=False,
                    closed_at__isnull=False,
                    verified_sign_count__isnull=False,
                ).order_by("-verified_at").first()
            )
            if (
                proof is None
                or proof.verified_at < now - PROOF_MAX_AGE
                or proof.verified_at > now
                or proof.verified_sign_count != credential.sign_count
                or proof.verified_at < registration.closed_at
            ):
                raise PermissionDenied("Fresh matching possession proof required.")
            evidence = OperatorWebAuthnEnrollmentApproval.objects.create(
                credential=credential, operator=operator, approver=actor,
                approver_role=authority[actor.pk], registration=registration,
                possession_proof=proof,
                identity_verification_reference=identity_verification_reference,
                approved_at=now,
            )
            credential.enrollment_verified_at = now
            credential.save(update_fields=["enrollment_verified_at", "updated_at"])
            return evidence
    except (DatabaseError, RuntimeError):
        raise PermissionDenied("Operator approval evidence unavailable.") from None
