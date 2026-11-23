"""Owner-approved Jireh household fee and offline submission quotation.

The $55 family charge is due at application submission. A quote is NOT proof
of a charge, payment, consent, processor response, or authorization. A future
transactional adapter must resolve the application from the authenticated
school/household/year and reconcile the provider's verified transaction.
No network calls or live payment activation are provided by this module.
"""

from dataclasses import dataclass
from uuid import UUID

HOUSEHOLD_APPLICATION_FEE_CENTS = 5_500
APPLICATION_FEE_PAYER = "family"
APPLICATION_FEE_SCOPE = "household"
APPLICATION_FEE_CHARGE_POINT = "submission"


class FeeObligationError(ValueError):
    """Invalid server-resolved application identity; no financial side effects."""


@dataclass(frozen=True, slots=True, repr=False)
class HouseholdApplicationFeeObligation:
    application_id: UUID
    school_id: UUID
    household_id: UUID
    academic_year_id: UUID
    obligation_key: str
    amount_cents: int = HOUSEHOLD_APPLICATION_FEE_CENTS
    currency: str = "USD"
    payer: str = APPLICATION_FEE_PAYER
    scope: str = "household_application"
    charge_point: str = APPLICATION_FEE_CHARGE_POINT


def quote_application_submission_fee(
    *, application_id: UUID, school_id: UUID, household_id: UUID, academic_year_id: UUID
) -> HouseholdApplicationFeeObligation:
    """Describe the one family fee due for an *already authorized* annual case.

    Caller MUST verify these identifiers match one persisted application and
    authorized household. This pure function grants nothing and never charges.
    Its stable local obligation key is NOT a provider idempotency key until
    the provider's exact contract and durable uniqueness rules are approved.
    """
    for key in (application_id, school_id, household_id, academic_year_id):
        if type(key) is not UUID or key.int == 0:
            raise FeeObligationError("fee_application_scope_invalid")
    return HouseholdApplicationFeeObligation(
        application_id=application_id,
        school_id=school_id,
        household_id=household_id,
        academic_year_id=academic_year_id,
        obligation_key=f"jireh:household-application-fee:v1:{application_id}",
    )
