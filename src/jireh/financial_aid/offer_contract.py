"""Fail-closed officer offer intent for synthetic standalone acceptance only.

No model, migration, route, persisted offer, payment or CROWN integration.
Trusted Django service code must independently derive the school/year,
application lifecycle, selected-student relationship and active staff grant.
NEVER pass request-supplied booleans as authorization evidence.
"""
from dataclasses import dataclass
from uuid import UUID

from .buckets import AidBucket
from .questionnaire_validation import QuestionnaireValidationError, validate_amount_cents


class OfferContractError(ValueError):
    """Stable non-sensitive validation code; no family or award details."""


@dataclass(frozen=True, slots=True, repr=False)
class OfficerOfferIntent:
    application_id: UUID
    student_id: UUID
    bucket: AidBucket
    amount_cents: int


def _strict_uuid(value: object) -> UUID:
    if type(value) is not str:
        raise OfferContractError("offer_uuid_invalid")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise OfferContractError("offer_uuid_invalid") from None
    if str(parsed) != value:
        raise OfferContractError("offer_uuid_invalid")
    return parsed


def validate_officer_offer_intent(
    *,
    director_authorized: object,
    application_in_authorized_school_year: object,
    application_status: object,
    student_selected_for_application: object,
    application_id: object,
    student_id: object,
    bucket: object,
    amount_cents: object,
    min_cents: object,
    max_cents: object,
) -> OfficerOfferIntent:
    """Validate a proposed offer without making, recording or confirming one.

    The approved financial policy must supply exact currency bounds before
    this contract is connected to a real financial case. Test values are
    fictional, not defaults or implied limits for a real applicant.
    """
    if director_authorized is not True:
        raise OfferContractError("offer_staff_access_denied")
    if application_in_authorized_school_year is not True:
        raise OfferContractError("offer_application_scope_denied")
    if type(application_status) is not str or application_status != "SUBMITTED":
        raise OfferContractError("offer_application_not_submitted")
    if student_selected_for_application is not True:
        raise OfferContractError("offer_student_not_selected")

    app_uuid = _strict_uuid(application_id)
    child_uuid = _strict_uuid(student_id)
    if type(bucket) is not str:
        raise OfferContractError("offer_bucket_invalid")
    try:
        aid_bucket = AidBucket(bucket)
    except ValueError:
        raise OfferContractError("offer_bucket_invalid") from None

    try:
        amount = validate_amount_cents(
            amount_cents, min_cents=min_cents, max_cents=max_cents
        )
    except QuestionnaireValidationError as exc:
        raise OfferContractError("offer_" + str(exc)) from None
    if amount <= 0:
        raise OfferContractError("offer_amount_not_positive")

    return OfficerOfferIntent(
        application_id=app_uuid, student_id=child_uuid,
        bucket=aid_bucket, amount_cents=amount,
    )
