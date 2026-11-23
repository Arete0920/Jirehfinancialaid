"""Pure, fail-closed submission intent contract for disposable synthetic testing.

No Django model, persistence, financial answer collection, HTTP route, audit,
consent text, payment, or production transition is activated by this module.
Authorization, approved disclosures, completeness, and audit must be enforced
by a future transactional server adapter before this contract may be used.
"""

from dataclasses import dataclass
from enum import StrEnum


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


def validate_submission_intent(
    *,
    current_state: object,
    accuracy_attested: object,
    consent_version: object,
    disclosure_is_approved: object,
    questionnaire_is_complete: object,
    authorized_household_scope: object,
) -> SubmissionIntent:
    """Validate caller-supplied gates for a synthetic submission *proposal*.

    Trusted server code must independently derive all boolean gates, consent
    version, actor and school/household/year from authenticated durable facts.
    Request JSON must NEVER be accepted directly for these trusted inputs.
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
    return SubmissionIntent(
        desired_state=ApplicationState.SUBMITTED,
        consent_version=consent_version,
        is_retry=state is ApplicationState.SUBMITTED,
    )
