"""Read-only school registry for the disposable privileged rehearsal.

Rows are restricted to immutable setup receipts belonging to the requesting
operator (proposer or approver). Source integrity is checked before reporting
metadata. This does not verify institutional consent, authorize activation,
create a grant, or expose any family, credential or financial information.
"""

from dataclasses import asdict, dataclass
from re import fullmatch
from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from .demo_preparation_jobs import _check_context, _verified_history
from .demo_platform_operations import OperationsPreviewIntegrityError, _saved_preparation_counts
from .demo_setup_intents import _candidate_evidence, _locked_setup_operator
from .models import (
    AcademicYear, FirstDirectorBootstrapRequest, OperatorWebAuthnActionIntent,
    School, SchoolGrantDecisionEvent, SchoolStaffAccess,
    SyntheticSchoolProvisioningReceipt,
)


_MAX_ROWS = 100


class RegistryIntegrityError(RuntimeError):
    """Registry evidence is unavailable or inconsistent."""


@dataclass(frozen=True, slots=True)
class SchoolRegistryRow:
    school_id: UUID
    code: str
    name: str
    timezone: str
    is_active: bool
    academic_year_count: int
    director_status: str
    active_director_count: int


def _valid_consumption(proof, receipt):
    challenge = proof.challenge
    return (
        proof.consumed_at is not None
        and challenge.operator_id == proof.operator_id
        and challenge.verified_at is not None
        and challenge.closed_at is not None
        and proof.expires_at == challenge.expires_at
        and challenge.verified_at <= proof.consumed_at < proof.expires_at
        and proof.consumed_at <= receipt.created_at
        and fullmatch(r"[0-9a-f]{64}", proof.payload_digest) is not None
    )


def _verify_receipt(receipt, school):
    setup = receipt.setup
    proposal, approval = receipt.proposal_proof, receipt.approval_proof
    history = _verified_history(setup)
    if (
        not history or history[-1].pk != receipt.preparation_id
        or history[-1].action != "PREPARED"
        or receipt.school_id != school.pk
        or not school.code.startswith("synthetic-")
        or proposal.pk == approval.pk
        or proposal.operator_id != setup.proposed_by_id
        or approval.operator_id == proposal.operator_id
        or proposal.action != OperatorWebAuthnActionIntent.ACTION_SETUP_PROPOSE
        or approval.action != OperatorWebAuthnActionIntent.ACTION_SETUP_APPROVE
        or not _valid_consumption(proposal, receipt)
        or not _valid_consumption(approval, receipt)
        or fullmatch(r"[0-9a-f]{64}", receipt.reference_digest) is None
    ):
        raise RegistryIntegrityError("School provisioning evidence inconsistent.")
    _, digest = _candidate_evidence({
        "code": school.code, "name": school.name, "timezone": school.timezone,
        "idempotency_key": str(setup.idempotency_key),
    }, privileged=True)
    if digest != setup.candidate_digest:
        raise RegistryIntegrityError("School identity no longer matches its receipt.")


def _director_readback(school):
    grants = list(SchoolStaffAccess.objects.for_school(school.pk).select_related("user"))
    approved = list(FirstDirectorBootstrapRequest.objects.filter(
        school=school, approved_at__isnull=False,
    )[:2])
    pending = FirstDirectorBootstrapRequest.objects.filter(
        school=school, approved_at__isnull=True, closed_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).exists()
    if len(approved) > 1 or bool(grants) != bool(approved):
        raise RegistryIntegrityError("First director approval evidence inconsistent.")
    if approved:
        request = approved[0]
        initial = next((grant for grant in grants if grant.pk == request.grant_id), None)
        if (
            initial is None or initial.user_id != request.subject_id
            or request.approved_by_id in (None, request.proposed_by_id, request.subject_id)
            or request.closed_at is not None or pending
            or not SchoolGrantDecisionEvent.objects.for_school(school.pk).filter(
                grant_id=initial.pk, scope_id=school.pk,
                target_user_id=request.subject_id, actor_user_id=request.approved_by_id,
                grant_kind=SchoolGrantDecisionEvent.KIND_STAFF,
                action=SchoolGrantDecisionEvent.ACTION_CREATED,
            ).exists()
        ):
            raise RegistryIntegrityError("Initial director grant evidence inconsistent.")

    active = sum(
        grant.is_active and grant.user.is_active
        and grant.role == SchoolStaffAccess.ROLE_AID_DIRECTOR for grant in grants
    )
    if any(grant.role != SchoolStaffAccess.ROLE_AID_DIRECTOR for grant in grants):
        raise RegistryIntegrityError("Unexpected staff role.")
    if not school.is_active:
        return "SCHOOL_INACTIVE", 0
    if active:
        return "DIRECTOR_ACCESS_AVAILABLE", active
    if grants:
        return "DIRECTOR_ACCESS_UNAVAILABLE", 0
    return ("DIRECTOR_APPROVAL_PENDING" if pending else "DIRECTOR_NOT_ASSIGNED"), 0


def read_synthetic_school_registry(*, operator):
    """Return scoped, bounded metadata from the actual disposable database.

    The school flag is a saved fact, never evidence of an approved activation.
    Do not infer live school readiness from this rehearsal.
    """
    # Only the new readback service may enter from the isolated operations
    # URLConf. Existing provisioning and bootstrap write guards are unchanged.
    from jireh.runtime.operator_portal_policy import OPERATIONS_URLCONF, operations_profile_available

    if settings.ROOT_URLCONF == OPERATIONS_URLCONF:
        if not operations_profile_available():
            raise PermissionDenied("Operations readback disabled.")
    else:
        _check_context(operator, privileged=True)
    try:
        with transaction.atomic(durable=True):
            actor = _locked_setup_operator(operator, privileged=True)
            receipts = list(SyntheticSchoolProvisioningReceipt.objects.filter(
                Q(setup__proposed_by=actor) | Q(approval_proof__operator=actor),
            ).select_related(
                "setup", "proposal_proof__challenge", "approval_proof__challenge",
            ).order_by("school_id")[:_MAX_ROWS + 1])
            if len(receipts) > _MAX_ROWS:
                raise RegistryIntegrityError("Registry exceeds the rehearsal limit.")
            result = []
            for receipt in receipts:
                school = School.objects.select_for_update().get(pk=receipt.school_id)
                _verify_receipt(receipt, school)
                status, active = _director_readback(school)
                result.append(SchoolRegistryRow(
                    school_id=school.pk, code=school.code, name=school.name,
                    timezone=school.timezone, is_active=school.is_active,
                    academic_year_count=AcademicYear.objects.for_school(school.pk).count(),
                    director_status=status, active_director_count=active,
                ))
            return tuple(result)
    except (DatabaseError, ValidationError, School.DoesNotExist):
        raise RegistryIntegrityError("School registry unavailable.") from None


def read_synthetic_preparation_counts(*, operator):
    """Read only the allowlisted operator's bounded, verified preparation history."""
    from jireh.runtime.operator_portal_policy import operations_profile_available

    if not operations_profile_available():
        raise PermissionDenied("Operations readback disabled.")
    try:
        with transaction.atomic(durable=True):
            # The preparation writers take the same operator lock before
            # changing any owned setup receipt or its append-only history.
            actor = _locked_setup_operator(operator, privileged=True)
            try:
                return _saved_preparation_counts(actor, max_rows=_MAX_ROWS)
            except (PermissionDenied, OperationsPreviewIntegrityError):
                raise RegistryIntegrityError("Preparation evidence unavailable.") from None
    except (DatabaseError, ValidationError):
        raise RegistryIntegrityError("Preparation evidence unavailable.") from None


@never_cache
@require_safe
def synthetic_school_registry(request):
    """Internal test-only HTTP readback; not routed in production or the demo."""
    try:
        rows = read_synthetic_school_registry(operator=request.user)
    except PermissionDenied:
        return JsonResponse({"detail": "Forbidden."}, status=403)
    except RegistryIntegrityError:
        return JsonResponse({"detail": "School registry unavailable."}, status=503)
    if request.GET:
        return JsonResponse({"detail": "Query parameters are not accepted."}, status=400)
    response = JsonResponse({"schools": [asdict(row) for row in rows]})
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response
