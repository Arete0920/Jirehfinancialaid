"""Pure validation-only school setup candidate for standalone Jireh.

Based on CROWN's strict input contract, not its TenantProfile or provisioning
engine. No database, HTTP, operator authorization, audit, payment, or school
creation occurs here. A valid candidate is NOT permission to provision.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID


_CODE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_TZ_SHAPE = re.compile(r"[A-Za-z][A-Za-z0-9_+\-]*(?:/[A-Za-z0-9_+\-]+){0,3}\Z")
_FIELDS = frozenset(("code", "name", "timezone", "idempotency_key"))


class SchoolSetupPreflightError(ValueError):
    """A candidate is malformed or attempts unsupported operations."""


@dataclass(frozen=True, slots=True)
class SchoolSetupCandidate:
    """Untrusted candidate. Not an approved provisioning instruction."""

    code: str
    name: str
    timezone: str
    idempotency_key: str


def validate_school_setup_candidate(payload: object) -> SchoolSetupCandidate:
    """Validate exact standalone School-shaped input without side effects.

    Domain/branding, plans, payment providers, SIS credentials, operator IDs,
    flags and arbitrary extra keys are deliberately rejected. Actual school
    creation additionally requires owner authorization, a trusted operator,
    canonical timezone verification, durable replay ownership, auditing,
    an approved data model, and an independent activation workflow.
    """
    if not isinstance(payload, Mapping) or set(payload) != _FIELDS:
        raise SchoolSetupPreflightError("Exactly four setup fields are required.")
    if any(type(payload[key]) is not str for key in _FIELDS):
        raise SchoolSetupPreflightError("Setup fields must be strings.")

    code, name = payload["code"], payload["name"]
    timezone, key = payload["timezone"], payload["idempotency_key"]
    if not 1 <= len(code) <= 64 or _CODE.fullmatch(code) is None:
        raise SchoolSetupPreflightError("Invalid school code.")
    if (
        not 1 <= len(name) <= 255
        or name != name.strip()
        or any(unicodedata.category(char).startswith("C") for char in name)
    ):
        raise SchoolSetupPreflightError("Invalid school name.")
    if not 1 <= len(timezone) <= 64 or _TZ_SHAPE.fullmatch(timezone) is None:
        raise SchoolSetupPreflightError("Invalid timezone shape.")
    # This checks shape only; the future authorized service must verify IANA
    # timezone identity against an independently selected canonical registry.
    try:
        uuid = UUID(key)
    except (ValueError, AttributeError, TypeError):
        raise SchoolSetupPreflightError("Invalid idempotency identifier.") from None
    if uuid.int == 0 or key != str(uuid):
        raise SchoolSetupPreflightError("Invalid idempotency identifier.")
    return SchoolSetupCandidate(code=code, name=name, timezone=timezone,
                                idempotency_key=key)
