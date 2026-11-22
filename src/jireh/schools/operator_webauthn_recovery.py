"""Disabled internal owner/integration-manager WebAuthn credential recovery.

Revokes one LOST or COMPROMISED approved key with immutable audit evidence.
Recovery does NOT authenticate operators, restore access, bypass registration,
or grant privilege. A replacement must be independently registered, prove
possession, and receive its ordinary identity approval before confirmation.
The human approver must verify external identity/authority; references
are evidence of attestation, never automatic identity proof.
"""

import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, transaction
from django.utils import timezone

from .login_budget import charge_bootstrap_operator_attempt
from .models import (
    OperatorWebAuthnCredential,
    OperatorWebAuthnEnrollmentApproval,
    OperatorWebAuthnRecovery,
    OperatorWebAuthnRecoveryReplacement,
)
from .operator_webauthn_approval import _approver_identity


_DIGEST = re.compile(r"\A[0-9a-f]{64}\Z")
_REFERENCE = re.compile(r"\A[A-Z0-9][A-Z0-9-]{11,119}\Z")


def _recovery_authorities():
    if getattr(settings, "JIREH_OPERATOR_CREDENTIAL_RECOVERY_ENABLED", False) is not True:
        raise PermissionDenied("Operator credential recovery disabled.")
    owner = getattr(settings, "JIREH_ENROLLMENT_OWNER_USER_ID", None)
    manager = getattr(settings, "JIREH_ENROLLMENT_MANAGER_USER_ID", None)
    if (type(owner) is not int or type(manager) is not int
            or owner <= 0 or manager <= 0 or owner == manager):
        raise PermissionDenied("Independent recovery authorities not configured.")
    return {
        owner: OperatorWebAuthnEnrollmentApproval.ROLE_OWNER,
        manager: OperatorWebAuthnEnrollmentApproval.ROLE_INTEGRATION_MANAGER,
    }


def _charge_recovery_attempt(approver):
    authorities = _recovery_authorities()
    if getattr(approver, "pk", None) not in authorities:
        raise PermissionDenied("Authorized recovery approver required.")
    try:
        # Debit outside the credential mutation. A failed password or invalid
        # reference MUST NOT refund a consumed operator attempt.
        with transaction.atomic(durable=True):
            allowed, _ = charge_bootstrap_operator_attempt(operator_id=approver.pk)
    except (DatabaseError, RuntimeError):
        raise PermissionDenied("Recovery attempt control unavailable.") from None
    if not allowed:
        raise PermissionDenied("Recovery attempt limit exceeded.")
    return authorities


def _verified_approver(*, approver, password, authorities):
    if not isinstance(password, str) or not 1 <= len(password) <= 1024:
        raise PermissionDenied("Approver reauthentication required.")
    actor = _approver_identity(approver, authorities)
    if not actor.check_password(password):
        raise PermissionDenied("Approver reauthentication failed.")
    return actor


def _check_reference(reference):
    if not isinstance(reference, str) or not _REFERENCE.fullmatch(reference):
        raise PermissionDenied("Independent identity-verification reference required.")


def _check_digest(digest):
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise PermissionDenied("Valid credential fingerprint required.")


def revoke_lost_operator_credential(
    *, approver, approver_password, operator_id, credential_id_digest,
    reason, identity_verification_reference,
):
    """Permanently revoke a lost/compromised active key and audit atomically.

    The target operator may be inactive: emergency revocation must not be
    blocked merely because an affected account was disabled. This operation
    NEVER activates or registers a replacement.
    """
    authorities = _charge_recovery_attempt(approver)
    _check_reference(identity_verification_reference)
    _check_digest(credential_id_digest)
    if reason not in (OperatorWebAuthnRecovery.REASON_LOST,
                      OperatorWebAuthnRecovery.REASON_COMPROMISED):
        raise PermissionDenied("Recovery reason invalid.")
    if type(operator_id) is not int or operator_id <= 0 or approver.pk == operator_id:
        raise PermissionDenied("Independent recovery authorization required.")
    try:
        with transaction.atomic(durable=True):
            authorities = _recovery_authorities()
            actor = _verified_approver(
                approver=approver, password=approver_password,
                authorities=authorities,
            )
            operator = (
                get_user_model()._default_manager.select_for_update()
                .filter(pk=operator_id).first()
            )
            if operator is None:
                raise PermissionDenied("Recovery operator unknown.")
            credential = (
                OperatorWebAuthnCredential.objects.select_for_update()
                .filter(
                    operator=operator,
                    credential_id_digest=credential_id_digest,
                    enrollment_verified_at__isnull=False,
                    revoked_at__isnull=True,
                ).first()
            )
            if credential is None:
                raise PermissionDenied("Active credential required for recovery.")
            now = timezone.now()
            credential.revoked_at = now
            credential.save(update_fields=["revoked_at", "updated_at"])
            return OperatorWebAuthnRecovery.objects.create(
                credential=credential, operator=operator, authorized_by=actor,
                approver_role=authorities[actor.pk],
                reason=reason,
                identity_verification_reference=identity_verification_reference,
                authorized_at=now,
            )
    except (DatabaseError, RuntimeError):
        raise PermissionDenied("Credential recovery storage unavailable.") from None


def confirm_recovery_replacement(
    *, approver, approver_password, recovery_id,
    replacement_credential_id_digest, confirmation_reference,
):
    """Record completed recovery only after standard enrollment/approval.

    The replacement credential is NEVER activated or authorized here. It must
    already have been registered since the loss, have fresh possession proof,
    and have an independently authorized approved enrollment record.
    """
    authorities = _charge_recovery_attempt(approver)
    _check_reference(confirmation_reference)
    _check_digest(replacement_credential_id_digest)
    try:
        with transaction.atomic(durable=True):
            authorities = _recovery_authorities()
            actor = _verified_approver(
                approver=approver, password=approver_password,
                authorities=authorities,
            )
            recovery = (
                OperatorWebAuthnRecovery.objects.select_for_update()
                .select_related("credential")
                .filter(pk=recovery_id).first()
            )
            if recovery is None or actor.pk == recovery.operator_id:
                raise PermissionDenied("Independent recovery confirmation required.")
            # Serialize replacement against registration/activation/revocation.
            operator = (
                get_user_model()._default_manager.select_for_update()
                .filter(pk=recovery.operator_id, is_active=True,
                        is_staff=True, is_superuser=True).first()
            )
            if operator is None:
                raise PermissionDenied("Eligible recovery operator required.")
            original = recovery.credential
            if original.revoked_at != recovery.authorized_at:
                raise PermissionDenied("Original credential revocation unverified.")
            replacement = (
                OperatorWebAuthnCredential.objects.select_for_update()
                .filter(
                    operator=operator,
                    credential_id_digest=replacement_credential_id_digest,
                    enrollment_verified_at__isnull=False,
                    revoked_at__isnull=True,
                ).first()
            )
            if (
                replacement is None or replacement.pk == original.pk
                or replacement.rp_id != original.rp_id
                or replacement.origin != original.origin
                or replacement.created_at <= recovery.authorized_at
                or replacement.enrollment_verified_at <= recovery.authorized_at
            ):
                raise PermissionDenied("Fresh independently enrolled replacement required.")
            approved = (
                OperatorWebAuthnEnrollmentApproval.objects
                .filter(
                    credential=replacement,
                    operator=operator,
                    approved_at=replacement.enrollment_verified_at,
                )
                .exists()
            )
            if not approved:
                raise PermissionDenied("Independently approved replacement required.")
            return OperatorWebAuthnRecoveryReplacement.objects.create(
                recovery=recovery, replacement_credential=replacement,
                operator=operator, confirmed_by=actor,
                approver_role=authorities[actor.pk],
                confirmation_reference=confirmation_reference,
                confirmed_at=timezone.now(),
            )
    except (DatabaseError, RuntimeError):
        raise PermissionDenied("Recovery confirmation storage unavailable.") from None
