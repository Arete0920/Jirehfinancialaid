"""Pure, fail-closed submission intent contract for disposable synthetic testing.

No Django model, persistence, financial answer collection, HTTP route, audit,
consent text, payment, or production transition is activated by this module.
Authorization, approved disclosures, completeness, and audit must be enforced
by a future transactional server adapter before this contract may be used.
"""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from .fees import (
    FeeObligationError,
    HouseholdApplicationFeeObligation,
    quote_application_submission_fee,
)


class SubmissionContractError(ValueError):
    """Return a stable non-sensitive error code, never applicant information."""


class ApplicationState(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"


@dataclass(frozen=True, slots=True, repr=False)
class SubmissionIntent:
    """An untrusted proposal, not proof of an authorized persisted submission."""

    desired_state: ApplicationState
    consent_version: str
    is_retry: bool


@dataclass(frozen=True, slots=True, repr=False)
class PendingPaymentIntent:
    """Readiness proposal bound to an authorized review, without persistence."""

    handoff_id: UUID
    review_revision: int
    consent_version: str
    fee_obligation: HouseholdApplicationFeeObligation

@dataclass(frozen=True, slots=True, repr=False)
class OfflinePaymentReconciliation:
    """Offline *test input*, never an authenticated or persisted payment receipt.

    Only trusted server code could later construct this from independently
    authenticated and durably reconciled provider evidence. Client JSON,
    browser redirects, a charge attempt, and this Python object are NOT proof.
    """

    application_id: UUID
    school_id: UUID
    household_id: UUID
    academic_year_id: UUID
    obligation_key: str
    amount_cents: int
    currency: str
    receipt_id: UUID
    terminal_success: bool
    source_authenticated: bool
    durably_reconciled: bool


def _validated_fee_obligation(fee_obligation: object) -> HouseholdApplicationFeeObligation:
    if type(fee_obligation) is not HouseholdApplicationFeeObligation:
        raise SubmissionContractError("submission_fee_obligation_invalid")
    try:
        expected = quote_application_submission_fee(
            application_id=fee_obligation.application_id,
            school_id=fee_obligation.school_id,
            household_id=fee_obligation.household_id,
            academic_year_id=fee_obligation.academic_year_id,
        )
    except FeeObligationError:
        raise SubmissionContractError("submission_fee_obligation_invalid") from None
    if fee_obligation != expected:
        raise SubmissionContractError("submission_fee_obligation_invalid")
    return expected


def _require_offline_reconciled_fee(*, fee_obligation: object, payment: object):
    """Check offline reconciliation structure; it does not authenticate a payment."""
    expected = _validated_fee_obligation(fee_obligation)
    if type(payment) is not OfflinePaymentReconciliation:
        raise SubmissionContractError("submission_payment_unreconciled")
    if (
        type(payment.application_id) is not UUID
        or payment.application_id != expected.application_id
        or type(payment.school_id) is not UUID
        or payment.school_id != expected.school_id
        or type(payment.household_id) is not UUID
        or payment.household_id != expected.household_id
        or type(payment.academic_year_id) is not UUID
        or payment.academic_year_id != expected.academic_year_id
        or type(payment.obligation_key) is not str
        or payment.obligation_key != expected.obligation_key
    ):
        raise SubmissionContractError("submission_payment_scope_mismatch")
    if type(payment.amount_cents) is not int or payment.amount_cents != expected.amount_cents:
        raise SubmissionContractError("submission_payment_amount_mismatch")
    if type(payment.currency) is not str or payment.currency != expected.currency:
        raise SubmissionContractError("submission_payment_currency_mismatch")
    if (
        type(payment.receipt_id) is not UUID
        or payment.receipt_id.int == 0
        or payment.terminal_success is not True
        or payment.source_authenticated is not True
        or payment.durably_reconciled is not True
    ):
        raise SubmissionContractError("submission_payment_unreconciled")

def _validate_review_gates(
    *, current_state, accuracy_attested, consent_version, disclosure_is_approved,
    questionnaire_is_complete, authorized_household_scope,
) -> ApplicationState:
    try:
        state = ApplicationState(current_state) if type(current_state) is str else None
    except ValueError:
        state = None
    if state is None:
        raise SubmissionContractError("submission_state_invalid")
    if disclosure_is_approved is not True:
        raise SubmissionContractError("submission_disclosure_not_approved")
    if (
        type(consent_version) is not str
        or not consent_version
        or consent_version != consent_version.strip()
        or len(consent_version) > 64
    ):
        raise SubmissionContractError("submission_consent_version_invalid")
    if accuracy_attested is not True:
        raise SubmissionContractError("submission_attestation_required")
    if authorized_household_scope is not True:
        raise SubmissionContractError("submission_access_denied")
    if questionnaire_is_complete is not True:
        raise SubmissionContractError("submission_incomplete")
    return state


def validate_pending_payment_intent(
    *, current_state: object, accuracy_attested: object, consent_version: object,
    disclosure_is_approved: object, questionnaire_is_complete: object,
    authorized_household_scope: object, fee_obligation: object,
    handoff_id: object, review_revision: object, handoff_is_current: object,
) -> PendingPaymentIntent:
    """Validate offline readiness to seek payment for an authorized draft.

    The trusted caller must resolve scope and freshness against the same
    saved handoff and review. A proposal carries no payment or state change.
    """
    state = _validate_review_gates(
        current_state=current_state, accuracy_attested=accuracy_attested,
        consent_version=consent_version, disclosure_is_approved=disclosure_is_approved,
        questionnaire_is_complete=questionnaire_is_complete,
        authorized_household_scope=authorized_household_scope,
    )
    if state is not ApplicationState.DRAFT:
        raise SubmissionContractError("submission_state_invalid")
    if (handoff_is_current is not True or type(handoff_id) is not UUID or handoff_id.int == 0
            or type(review_revision) is not int or review_revision < 1):
        raise SubmissionContractError("submission_handoff_required")
    return PendingPaymentIntent(
        handoff_id=handoff_id, review_revision=review_revision, consent_version=consent_version,
        fee_obligation=_validated_fee_obligation(fee_obligation),
    )


def validate_submission_intent(
    *, current_state: object, accuracy_attested: object, consent_version: object,
    disclosure_is_approved: object, questionnaire_is_complete: object,
    authorized_household_scope: object, fee_obligation: object, payment_reconciliation: object,
) -> SubmissionIntent:
    """Validate a synthetic proposal. A trusted adapter must derive every gate.

    These inputs must come from authorized, durable facts independent of
    request JSON. Offline reconciliation is structural evidence only.
    """
    state = _validate_review_gates(
        current_state=current_state, accuracy_attested=accuracy_attested,
        consent_version=consent_version, disclosure_is_approved=disclosure_is_approved,
        questionnaire_is_complete=questionnaire_is_complete,
        authorized_household_scope=authorized_household_scope,
    )
    _require_offline_reconciled_fee(
        fee_obligation=fee_obligation, payment=payment_reconciliation
    )
    return SubmissionIntent(
        desired_state=ApplicationState.SUBMITTED,
        consent_version=consent_version,
        is_retry=state is ApplicationState.SUBMITTED,
    )
