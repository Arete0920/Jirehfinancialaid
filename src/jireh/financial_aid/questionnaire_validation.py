"""Policy-parameterized financial questionnaire value validation.

Side-effect-free primitives only. The product owner's seven-section approval
does NOT approve monetary bounds, reporting periods, questionnaire fields,
retention, consent text or financial scoring.

These functions require explicit caller-supplied numeric bounds and do not
authorize a household, store answers, accept attachments, grant reuse consent,
expose HTTP routes, or convert periods into annual income. Do not connect to
real family data until the separate privacy and policy gates pass.
"""

import re
from dataclasses import dataclass
from datetime import date


_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")


class QuestionnaireValidationError(ValueError):
    """A stable, non-sensitive error code; never echo submitted values."""


@dataclass(frozen=True, slots=True, repr=False)
class ValidatedFlow:
    """Money for an explicitly supplied interval, not annualized."""

    amount_cents: int
    period_start: date
    period_end: date


@dataclass(frozen=True, slots=True, repr=False)
class ValidatedBalance:
    """Money held/owed at a specific date, never treated as annual flow."""

    balance_cents: int
    as_of_date: date


def validate_amount_cents(
    value: object, *, min_cents: int, max_cents: int
) -> int:
    """Require integer cents and *explicit* owner-approved caller limits.

    No implicit zeros, abs(), rounding, currency conversion or bound defaults.
    A caller must set both limits from a separately approved field policy;
    the values in tests are synthetic and are NOT product-wide policy.
    """
    if type(min_cents) is not int or type(max_cents) is not int:
        raise QuestionnaireValidationError("money_bounds_not_configured")
    if min_cents > max_cents:
        raise QuestionnaireValidationError("money_bounds_invalid")
    if type(value) is not int:
        raise QuestionnaireValidationError("amount_type_invalid")
    if not min_cents <= value <= max_cents:
        raise QuestionnaireValidationError("amount_out_of_range")
    return value


def _strict_iso_date(value: object) -> date:
    """Accept only an actual YYYY-MM-DD calendar date, not a timestamp."""
    if type(value) is not str or _ISO_DATE.fullmatch(value) is None:
        raise QuestionnaireValidationError("date_invalid")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise QuestionnaireValidationError("date_invalid") from None


def validate_flow(
    *,
    amount_cents: object,
    period_start: object,
    period_end: object,
    min_cents: int,
    max_cents: int,
) -> ValidatedFlow:
    """Validate flow shape without guessing reporting year or annualization."""
    amount = validate_amount_cents(
        amount_cents, min_cents=min_cents, max_cents=max_cents
    )
    start = _strict_iso_date(period_start)
    end = _strict_iso_date(period_end)
    if end < start:
        raise QuestionnaireValidationError("flow_period_inverted")
    return ValidatedFlow(
        amount_cents=amount, period_start=start, period_end=end
    )


def validate_calendar_year_flow(
    *,
    reporting_year: object,
    amount_cents: object,
    period_start: object,
    period_end: object,
    min_cents: int,
    max_cents: int,
) -> ValidatedFlow:
    """Validate a flow against a caller-selected, separately authorized year.

    Does not choose the applicable school tax year, split crossing periods,
    annualize, authorize households, or persist financial answers.
    """
    if type(reporting_year) is not int or not 1 <= reporting_year <= 9999:
        raise QuestionnaireValidationError("reporting_year_invalid")
    flow = validate_flow(
        amount_cents=amount_cents,
        period_start=period_start,
        period_end=period_end,
        min_cents=min_cents,
        max_cents=max_cents,
    )
    if (
        flow.period_start.year != reporting_year
        or flow.period_end.year != reporting_year
    ):
        raise QuestionnaireValidationError("flow_outside_reporting_year")
    return flow


def validate_balance(
    *,
    balance_cents: object,
    as_of_date: object,
    min_cents: int,
    max_cents: int,
) -> ValidatedBalance:
    """Validate dated balance shape; no annual amount or exclusion rules."""
    amount = validate_amount_cents(
        balance_cents, min_cents=min_cents, max_cents=max_cents
    )
    return ValidatedBalance(
        balance_cents=amount, as_of_date=_strict_iso_date(as_of_date)
    )


def validate_optional_consent(value: object) -> bool | None:
    """Preserve unanswered (None), explicit refusal (False), and opt-in (True).

    An explicit True is still NOT sufficient legal authorization to reuse,
    disclose, or attest: that additionally needs purpose, consent version,
    authenticated authorized actor, school/year scope and durable audit.
    """
    if value is None or type(value) is bool:
        return value
    raise QuestionnaireValidationError("consent_type_invalid")
