"""Pure, versioned five-bucket *candidate* assessment arithmetic.

Every coefficient, bucket cap, permitted basis, rounding rule, school/year,
and aggregate review ceiling is supplied by the caller. This module DOES NOT
determine eligible income, assets, need, mission criteria, award authority,
school grants, legal compliance or whether a school has approved a policy.

Only synthetic/trusted offline inputs may be used until real questionnaire,
privacy, methodology and school decision gates are separately approved.
No Django, CROWN, database, routes, payments or automatic award posting.
"""
import re
from dataclasses import dataclass
from uuid import UUID

from .buckets import AidBucket


_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_ROUNDING = frozenset(("FLOOR", "HALF_UP", "CEILING"))
_CONTRACT_VERSION = "synthetic-arithmetic-v1"


class CandidateAssessmentError(ValueError):
    """Stable code only; never incorporates applicant financial values."""


def _reject(code: str):
    raise CandidateAssessmentError(code)


def _uuid(value: object, *, error_code: str) -> UUID:
    if type(value) is not str:
        _reject(error_code)
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError):
        _reject(error_code)
    if str(parsed) != value or parsed.int == 0:
        _reject(error_code)
    return parsed


def _cents(value: object, *, error_code: str) -> int:
    if type(value) is not int or value < 0:
        _reject(error_code)
    return value


@dataclass(frozen=True, slots=True, repr=False)
class BucketCalculationRule:
    """A caller-provided *synthetic* ratio, not a default Jireh policy."""

    bucket: AidBucket
    numerator: int
    denominator: int
    rounding: str
    maximum_basis_cents: int
    maximum_recommendation_cents: int


@dataclass(frozen=True, slots=True, repr=False)
class CandidateAssessmentPolicy:
    """Explicit policy parameters; constructing this is NOT policy approval."""

    school_id: str
    academic_year_id: str
    policy_version: str
    bucket_rules: tuple[BucketCalculationRule, ...]
    total_review_ceiling_cents: int


@dataclass(frozen=True, slots=True, repr=False)
class CandidateAssessmentLine:
    bucket: AidBucket
    basis_cents: int
    numerator: int
    denominator: int
    rounding: str
    uncapped_cents: int
    recommendation_cents: int
    cap_applied: bool


@dataclass(frozen=True, slots=True, repr=False)
class CandidateAssessment:
    """An explainable preview, never a school-authorized or promised award."""

    policy_version: str
    calculation_version: str
    school_id: UUID
    academic_year_id: UUID
    lines: tuple[CandidateAssessmentLine, ...]
    total_recommendation_cents: int
    requires_school_authorization: bool


def _validate_policy(policy: object) -> tuple[UUID, UUID]:
    if type(policy) is not CandidateAssessmentPolicy:
        _reject("candidate_policy_missing")
    school_id = _uuid(
        policy.school_id, error_code="candidate_policy_school_invalid"
    )
    academic_year_id = _uuid(
        policy.academic_year_id, error_code="candidate_policy_year_invalid"
    )
    if (
        type(policy.policy_version) is not str
        or _VERSION.fullmatch(policy.policy_version) is None
    ):
        _reject("candidate_policy_version_invalid")
    _cents(
        policy.total_review_ceiling_cents,
        error_code="candidate_policy_total_ceiling_invalid",
    )
    if (
        type(policy.bucket_rules) is not tuple
        or len(policy.bucket_rules) != len(AidBucket)
    ):
        _reject("candidate_policy_bucket_set_invalid")
    found = set()
    for rule in policy.bucket_rules:
        if type(rule) is not BucketCalculationRule:
            _reject("candidate_policy_bucket_rule_invalid")
        if type(rule.bucket) is not AidBucket or rule.bucket in found:
            _reject("candidate_policy_bucket_set_invalid")
        found.add(rule.bucket)
        if (
            type(rule.denominator) is not int
            or not 1 <= rule.denominator <= 1_000_000
            or type(rule.numerator) is not int
            or not 0 <= rule.numerator <= rule.denominator
        ):
            _reject("candidate_policy_ratio_invalid")
        if type(rule.rounding) is not str or rule.rounding not in _ROUNDING:
            _reject("candidate_policy_rounding_invalid")
        _cents(
            rule.maximum_basis_cents,
            error_code="candidate_policy_basis_ceiling_invalid",
        )
        _cents(
            rule.maximum_recommendation_cents,
            error_code="candidate_policy_bucket_ceiling_invalid",
        )
    if found != set(AidBucket):
        _reject("candidate_policy_bucket_set_invalid")
    return school_id, academic_year_id


def _rounded_nonnegative(numerator: int, denominator: int, mode: str) -> int:
    if mode == "FLOOR":
        return numerator // denominator
    if mode == "CEILING":
        return (numerator + denominator - 1) // denominator
    # HALF_UP: exact integer arithmetic, no floats or implicit banker's rounding
    return (2 * numerator + denominator) // (2 * denominator)


def calculate_candidate_assessment(
    *,
    policy: CandidateAssessmentPolicy,
    school_id: object,
    academic_year_id: object,
    basis_cents_by_bucket: object,
) -> CandidateAssessment:
    """Return an explainable, unposted simulation from explicit inputs.

    School/year equality is an input-integrity check only, NOT authentication
    or authorization; real services must independently derive all parameters
    from approved school policy and verified household/grant records.

    A sum above the explicit review ceiling fails closed rather than silently
    prorating, trimming or turning recommendations into binding school awards.
    """
    expected_school, expected_year = _validate_policy(policy)
    actual_school = _uuid(
        school_id, error_code="candidate_scope_school_invalid"
    )
    actual_year = _uuid(
        academic_year_id, error_code="candidate_scope_year_invalid"
    )
    if expected_school != actual_school or expected_year != actual_year:
        _reject("candidate_policy_scope_mismatch")
    if (
        type(basis_cents_by_bucket) is not dict
        or any(type(key) is not AidBucket for key in basis_cents_by_bucket)
        or set(basis_cents_by_bucket) != set(AidBucket)
    ):
        _reject("candidate_basis_bucket_set_invalid")

    rules = {rule.bucket: rule for rule in policy.bucket_rules}
    lines = []
    total = 0
    for bucket in AidBucket:
        rule = rules[bucket]
        basis = _cents(
            basis_cents_by_bucket[bucket],
            error_code="candidate_basis_amount_invalid",
        )
        if basis > rule.maximum_basis_cents:
            _reject("candidate_basis_exceeds_ceiling")

        uncapped = _rounded_nonnegative(
            basis * rule.numerator, rule.denominator, rule.rounding
        )
        recommendation = min(uncapped, rule.maximum_recommendation_cents)
        total += recommendation
        lines.append(
            CandidateAssessmentLine(
                bucket=bucket,
                basis_cents=basis,
                numerator=rule.numerator,
                denominator=rule.denominator,
                rounding=rule.rounding,
                uncapped_cents=uncapped,
                recommendation_cents=recommendation,
                cap_applied=recommendation < uncapped,
            )
        )
    if total > policy.total_review_ceiling_cents:
        _reject("candidate_total_exceeds_review_ceiling")

    return CandidateAssessment(
        policy_version=policy.policy_version,
        calculation_version=_CONTRACT_VERSION,
        school_id=actual_school,
        academic_year_id=actual_year,
        lines=tuple(lines),
        total_recommendation_cents=total,
        requires_school_authorization=True,
    )
