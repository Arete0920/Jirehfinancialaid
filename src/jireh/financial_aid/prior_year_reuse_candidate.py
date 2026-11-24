"""Non-persistent, synthetic-only preflight for CROWN-style prior-year reuse.

CROWN profile_service.py at 46b56609fe18360299b08eabaa8bccdffb356a0e
checks a reuse preference but does not verify destination-school alignment
inside carry_forward_profile. This standalone contract checks explicit scopes,
actor-bound access and purpose/version-bound consent from a *trusted caller*.
It cannot authenticate grants, validate legal consent, authorize a migration,
read/copy financial answers, or enable reuse in a customer application.
Q01-Q10 policy and release gates remain unresolved.
"""

from dataclasses import dataclass
from uuid import UUID


class ReusePreflightError(ValueError):
    """Stable nonsensitive code; never include user identifiers or answers."""


@dataclass(frozen=True, slots=True, repr=False)
class AnnualScope:
    school_id: str
    household_id: str
    academic_year_id: str
    application_id: str


@dataclass(frozen=True, slots=True, repr=False)
class ScopedAccessEvidence:
    scope: AnnualScope
    actor_id: str
    active: bool


@dataclass(frozen=True, slots=True, repr=False)
class ReuseConsentEvidence:
    source_scope: AnnualScope
    actor_id: str
    purpose: str
    version: str
    accepted: bool
    withdrawn: bool


@dataclass(frozen=True, slots=True, repr=False)
class SyntheticReusePreview:
    """No financial content and no authority to write or submit."""
    source_provenance: str = "PRIOR_YEAR"
    copied_items_must_be_unverified: bool = True
    current_year_attestation_satisfied: bool = False
    production_reuse_authorized: bool = False
    data_written: bool = False


def _id(value: object) -> str:
    if type(value) is not str:
        raise ReusePreflightError("reuse_scope_invalid")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise ReusePreflightError("reuse_scope_invalid") from None
    if str(parsed) != value or parsed.int == 0:
        raise ReusePreflightError("reuse_scope_invalid")
    return value


def _scope(value: object) -> AnnualScope:
    if type(value) is not AnnualScope:
        raise ReusePreflightError("reuse_scope_invalid")
    for field in ("school_id", "household_id", "academic_year_id", "application_id"):
        _id(getattr(value, field))
    return value


def _label(value: object) -> bool:
    return type(value) is str and bool(value) and value.strip() == value


def preview_prior_year_reuse(
    *,
    source: object,
    target: object,
    acting_user_id: object,
    source_access: object,
    target_access: object,
    consent: object,
    authorized_purpose: object,
    authorized_version: object,
    source_precedes_target: object,
) -> SyntheticReusePreview:
    """Check caller-supplied *trusted* evidence for synthetic design only.

    The eventual server adapter must independently load and validate both
    grants, the approved version/purpose, chronology, and the consent record.
    None may be accepted from client JSON. This returns no row/permission data.
    """
    source = _scope(source)
    target = _scope(target)
    actor = _id(acting_user_id)

    if source.school_id != target.school_id or source.household_id != target.household_id:
        raise ReusePreflightError("reuse_cross_scope_denied")
    if source.academic_year_id == target.academic_year_id or source.application_id == target.application_id:
        raise ReusePreflightError("reuse_same_period_denied")
    if source_precedes_target is not True:
        raise ReusePreflightError("reuse_chronology_unverified")

    for evidence, expected in ((source_access, source), (target_access, target)):
        if (
            type(evidence) is not ScopedAccessEvidence
            or evidence.active is not True
            or evidence.scope != expected
            or evidence.actor_id != actor
        ):
            raise ReusePreflightError("reuse_access_denied")

    if not (_label(authorized_purpose) and _label(authorized_version)):
        raise ReusePreflightError("reuse_policy_missing")
    if (
        type(consent) is not ReuseConsentEvidence
        or consent.source_scope != source
        or consent.actor_id != actor
        or consent.accepted is not True
        or consent.withdrawn is not False
        or consent.purpose != authorized_purpose
        or consent.version != authorized_version
    ):
        raise ReusePreflightError("reuse_consent_denied")
    return SyntheticReusePreview()
