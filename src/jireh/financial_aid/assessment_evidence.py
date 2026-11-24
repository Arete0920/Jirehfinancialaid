"""Scope and provenance checks for offline fictional assessment snapshots."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from .assessment_contract import (
    _VERSION, CandidateAssessment, CandidateAssessmentPolicy, _cents, _reject,
    _uuid, _validate_policy, calculate_candidate_assessment,
)
from .buckets import AidBucket


class EvidenceState(StrEnum):
    READY = "ready"
    MISSING = "missing"
    UNVERIFIED = "unverified"
    INELIGIBLE = "ineligible"
    STALE = "stale"


@dataclass(frozen=True, slots=True, repr=False)
class FictionalBucketEvidence:
    bucket: AidBucket
    state: EvidenceState
    source_id: str | None = None
    source_revision: int | None = None
    basis_cents: int | None = None


@dataclass(frozen=True, slots=True, repr=False)
class FictionalAssessmentEvidence:
    school_id: str
    academic_year_id: str
    application_id: str
    version: str
    revision: int
    buckets: tuple[FictionalBucketEvidence, ...]


@dataclass(frozen=True, slots=True)
class EvidenceSignal:
    """Advisory status and provenance without financial values."""

    bucket: AidBucket
    state: EvidenceState
    source_id: UUID | None
    source_revision: int | None


@dataclass(frozen=True, slots=True, repr=False)
class FictionalAssessmentReport:
    school_id: UUID
    academic_year_id: UUID
    application_id: UUID
    policy_version: str
    evidence_version: str
    evidence_revision: int
    signals: tuple[EvidenceSignal, ...]
    assessment: CandidateAssessment | None


def _evidence_signal(row, revision):
    if type(row.state) is not EvidenceState or row.state is EvidenceState.STALE:
        _reject("candidate_evidence_state_invalid")
    if row.state is EvidenceState.MISSING:
        if any(value is not None for value in (row.source_id, row.source_revision, row.basis_cents)):
            _reject("candidate_evidence_missing_has_values")
        return EvidenceSignal(row.bucket, row.state, None, None)
    source_id = _uuid(row.source_id, error_code="candidate_evidence_source_invalid")
    if type(row.source_revision) is not int or not 1 <= row.source_revision <= revision:
        _reject("candidate_evidence_source_revision_invalid")
    if row.state is EvidenceState.READY:
        _cents(row.basis_cents, error_code="candidate_basis_amount_invalid")
    elif row.basis_cents is not None:
        _reject("candidate_evidence_unavailable_has_amount")
    state = EvidenceState.STALE if row.source_revision < revision else row.state
    return EvidenceSignal(row.bucket, state, source_id, row.source_revision)


def assess_fictional_evidence(
    *, snapshot: FictionalAssessmentEvidence, policy: CandidateAssessmentPolicy,
    school_id: str, academic_year_id: str, application_id: str,
    expected_version: str, expected_revision: int,
) -> FictionalAssessmentReport:
    """Use independently authorized scope. Withhold calculation if any bucket is unresolved.

    This fixture contract determines staleness by revision. It supplies neither
    time-based freshness policy nor eligibility or verification decisions.
    """
    policy_school, policy_year = _validate_policy(policy)
    actual_school = _uuid(school_id, error_code="candidate_scope_school_invalid")
    actual_year = _uuid(academic_year_id, error_code="candidate_scope_year_invalid")
    actual_application = _uuid(application_id, error_code="candidate_scope_application_invalid")
    if (actual_school, actual_year) != (policy_school, policy_year):
        _reject("candidate_policy_scope_mismatch")
    if type(snapshot) is not FictionalAssessmentEvidence:
        _reject("candidate_evidence_invalid")
    for actual, bound in (
        (actual_school, snapshot.school_id), (actual_year, snapshot.academic_year_id),
        (actual_application, snapshot.application_id),
    ):
        if actual != _uuid(bound, error_code="candidate_evidence_scope_invalid"):
            _reject("candidate_evidence_scope_mismatch")
    if any(type(version) is not str or _VERSION.fullmatch(version) is None
           for version in (expected_version, snapshot.version)):
        _reject("candidate_evidence_version_invalid")
    if snapshot.version != expected_version:
        _reject("candidate_evidence_version_mismatch")
    if (type(expected_revision) is not int or expected_revision < 0
            or type(snapshot.revision) is not int or snapshot.revision != expected_revision):
        _reject("candidate_evidence_revision_mismatch")
    if (type(snapshot.buckets) is not tuple or len(snapshot.buckets) != len(AidBucket)
            or any(type(row) is not FictionalBucketEvidence or type(row.bucket) is not AidBucket
                   for row in snapshot.buckets)):
        _reject("candidate_evidence_bucket_set_invalid")
    rows = {row.bucket: row for row in snapshot.buckets}
    if set(rows) != set(AidBucket):
        _reject("candidate_evidence_bucket_set_invalid")

    signals = tuple(_evidence_signal(rows[bucket], snapshot.revision) for bucket in AidBucket)
    ceilings = {rule.bucket: rule.maximum_basis_cents for rule in policy.bucket_rules}
    basis = {}
    for signal in signals:
        if signal.state is EvidenceState.READY:
            amount = rows[signal.bucket].basis_cents
            if amount > ceilings[signal.bucket]:
                _reject("candidate_basis_exceeds_ceiling")
            basis[signal.bucket] = amount
    assessment = None
    if len(basis) == len(AidBucket):
        assessment = calculate_candidate_assessment(
            policy=policy, school_id=school_id, academic_year_id=academic_year_id,
            basis_cents_by_bucket=basis,
        )
    return FictionalAssessmentReport(
        actual_school, actual_year, actual_application, policy.policy_version,
        snapshot.version, snapshot.revision, signals, assessment,
    )
