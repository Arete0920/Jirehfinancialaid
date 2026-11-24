"""Pure preflight for a *synthetic* financial-document metadata proposal.

No file bytes, file name, financial answers, persistence, object storage,
malware scanner, cloud service, upload token or public route is implemented.

An HTTP header or request field cannot authorize a school, prove a MIME type,
establish a scan result or approve a document type. A future trusted service
must derive those facts independently after owner-approved storage/security
policy and authenticated school/household/application authorization.
"""
from dataclasses import dataclass
from re import fullmatch
from uuid import UUID


class DocumentPreflightError(ValueError):
    """Stable, non-sensitive validation code only."""


def _deny(code: str):
    raise DocumentPreflightError(code)


def _canonical_uuid(value: object, code: str) -> UUID:
    if type(value) is not str:
        _deny(code)
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError):
        _deny(code)
    if str(parsed) != value or parsed.int == 0:
        _deny(code)
    return parsed


def _positive_limit(value: object, code: str) -> int:
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        _deny(code)
    return value


@dataclass(frozen=True, slots=True, repr=False)
class CandidateDocumentPolicy:
    """Explicit fictional review inputs, not authorization to accept uploads."""

    policy_version: str
    school_id: str
    academic_year_id: str
    allowed_declared_media_types: tuple[str, ...]
    maximum_bytes: int


@dataclass(frozen=True, slots=True, repr=False)
class CandidateDocumentPreflight:
    """Non-operational shape check; no executable upload or storage permission."""

    policy_version: str
    school_id: UUID
    academic_year_id: UUID
    household_id: UUID
    application_id: UUID
    claimed_media_type: str
    claimed_byte_count: int
    claimed_sha256: str
    requires_trusted_access_check: bool
    requires_server_side_type_detection: bool
    requires_malware_scan: bool
    requires_approved_encrypted_storage: bool
    storage_permitted: bool


def validate_document_candidate(
    *,
    policy: object,
    school_id: object,
    academic_year_id: object,
    household_id: object,
    application_id: object,
    claimed_media_type: object,
    claimed_byte_count: object,
    claimed_sha256: object,
) -> CandidateDocumentPreflight:
    """Validate bounded synthetic metadata; never inspect or authorize bytes."""
    if type(policy) is not CandidateDocumentPolicy:
        _deny("document_policy_missing")
    if (
        type(policy.policy_version) is not str
        or fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", policy.policy_version) is None
    ):
        _deny("document_policy_version_invalid")
    approved_school = _canonical_uuid(
        policy.school_id, "document_policy_school_invalid"
    )
    approved_year = _canonical_uuid(
        policy.academic_year_id, "document_policy_year_invalid"
    )
    requested_school = _canonical_uuid(school_id, "document_school_invalid")
    requested_year = _canonical_uuid(
        academic_year_id, "document_year_invalid"
    )
    household = _canonical_uuid(household_id, "document_household_invalid")
    application = _canonical_uuid(
        application_id, "document_application_invalid"
    )
    if (
        approved_school != requested_school
        or approved_year != requested_year
    ):
        _deny("document_policy_scope_mismatch")

    if (
        type(policy.allowed_declared_media_types) is not tuple
        or not policy.allowed_declared_media_types
        or any(
            type(t) is not str
            or not t
            or len(t) > 127
            or fullmatch(r"[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*", t)
            is None
            for t in policy.allowed_declared_media_types
        )
        or len(set(policy.allowed_declared_media_types))
        != len(policy.allowed_declared_media_types)
    ):
        _deny("document_media_policy_missing")
    maximum_bytes = _positive_limit(
        policy.maximum_bytes, "document_size_policy_missing"
    )
    if (
        type(claimed_media_type) is not str
        or claimed_media_type not in policy.allowed_declared_media_types
    ):
        _deny("document_claimed_media_type_not_allowed")
    byte_count = _positive_limit(
        claimed_byte_count, "document_claimed_size_invalid"
    )
    if byte_count > maximum_bytes:
        _deny("document_claimed_size_exceeds_policy")
    if (
        type(claimed_sha256) is not str
        or fullmatch(r"[0-9a-f]{64}", claimed_sha256) is None
    ):
        _deny("document_claimed_digest_invalid")

    # All checked values are client-claim shapes, NOT trusted proof. This
    # returned object cannot authorize writing, retrieval or release.
    return CandidateDocumentPreflight(
        policy_version=policy.policy_version,
        school_id=requested_school,
        academic_year_id=requested_year,
        household_id=household,
        application_id=application,
        claimed_media_type=claimed_media_type,
        claimed_byte_count=byte_count,
        claimed_sha256=claimed_sha256,
        requires_trusted_access_check=True,
        requires_server_side_type_detection=True,
        requires_malware_scan=True,
        requires_approved_encrypted_storage=True,
        storage_permitted=False,
    )
