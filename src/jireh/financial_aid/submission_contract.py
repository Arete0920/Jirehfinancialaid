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


def _require_offline_reconciled_fee(*, fee_obligation: object, payment: object):
    """Fail closed on any missing, mismatched, or unconfirmed $55 obligation.

    Offline structural contract ONLY: checks cannot authenticate a payment
    provider or make an untrusted reconciliation fact true. A future server
    adapter must establish source authenticity, replay protection, durable
    uniqueness and application linkage without accepting client claims.
    """
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

def validate_submission_intent(
    *,
    current_state: object,
    accuracy_attested: object,
    consent_version: object,
    disclosure_is_approved: object,
    questionnaire_is_complete: object,
    authorized_household_scope: object,
    fee_obligation: object,
    payment_reconciliation: object,
) -> SubmissionIntent:
    """Validate caller-supplied gates for a synthetic submission *proposal*.

    Trusted server code must independently derive all boolean gates, consent
    version, actor, school/household/year and payment reconciliation from
    authenticated durable facts. Request JSON must NEVER be accepted directly
    for these trusted inputs. The offline record is NOT payment proof.
    This function does not write or signal that an application was submitted.
    """
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
    _require_offline_reconciled_fee(
        fee_obligation=fee_obligation, payment=payment_reconciliation
    )
    return SubmissionIntent(
        desired_state=ApplicationState.SUBMITTED,
        consent_version=consent_version,
        is_retry=state is ApplicationState.SUBMITTED,
    )
