"""Read-only submission readiness for an authorized fictional draft."""

from dataclasses import dataclass
from uuid import UUID

from .fees import quote_application_submission_fee
from .submission_contract import ApplicationState
from .synthetic_application_review import read_fictional_application_review


@dataclass(frozen=True, slots=True, repr=False)
class FictionalSubmissionPreflight:
    application_id: UUID
    application_state: ApplicationState
    questionnaire_revision: int
    fee_amount_cents: int
    fee_currency: str
    blocking_codes: tuple[str, ...]


def read_fictional_submission_preflight(
    *, user, school_id, household_id, academic_year_id, key,
) -> FictionalSubmissionPreflight:
    """Use the latest saved review for this actor and annual household draft.

    The fictional review is rehearsal evidence. Legal disclosure approval and
    authenticated, durable payment reconciliation are unavailable in this flow.
    """
    review = read_fictional_application_review(
        user=user, school_id=school_id, household_id=household_id,
        academic_year_id=academic_year_id, key=key,
    )
    draft = review["draft"]
    fee = quote_application_submission_fee(
        application_id=draft.pk, school_id=draft.school_id,
        household_id=draft.household_id, academic_year_id=draft.academic_year_id,
    )
    blockers = []
    if review["reasons"]:
        blockers.append("submission_review_incomplete")
    elif review["confirmation"] is None:
        blockers.append("submission_review_confirmation_required")
    blockers.extend(("submission_disclosure_not_approved", "submission_payment_unreconciled"))

    return FictionalSubmissionPreflight(
        application_id=draft.pk,
        application_state=ApplicationState(draft.status),
        questionnaire_revision=review["revision"],
        fee_amount_cents=fee.amount_cents,
        fee_currency=fee.currency,
        blocking_codes=tuple(blockers),
    )
