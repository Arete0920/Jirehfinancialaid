"""Offline, fail-closed audit of evidence packet completeness for release gates.

This module never certifies a deployed environment or authorizes release.
Even a structurally complete packet remains NO-GO until independent human
review, trusted artifact inspection, operational testing and explicit approval.
No network, credentials, environment mutation, Django or cloud dependencies.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from re import fullmatch

GATE_IDS = ("D1", "D2", "D3", "T1", "T2", "S1", "S2", "M1", "M2", "I1", "A1")
EXPECTED_KEYS = frozenset((
    "gate", "status", "release_sha", "environment", "owner",
    "reviewer", "tested_at", "artifact_ref",
))
RECORD_STATUSES = frozenset(("NOT_TESTED", "FAILED", "PASS"))
_SAFE_REF = r"[A-Za-z0-9][A-Za-z0-9._:/#?=&%+@-]{7,511}"
_ID = r"[A-Za-z0-9][A-Za-z0-9._-]{2,127}"


@dataclass(frozen=True, slots=True)
class GateAudit:
    gate: str
    recorded_status: str
    evidence_complete: bool
    blocking_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReleaseEvidenceAudit:
    release_sha: str | None
    environment: str | None
    gates: tuple[GateAudit, ...]
    packet_complete: bool
    disposition: str
    needs_independent_human_review: bool
    authorizes_release: bool


def _valid_identifier(value: object) -> bool:
    return type(value) is str and fullmatch(_ID, value) is not None


def _valid_utc_timestamp(value: object) -> bool:
    if type(value) is not str or len(value) > 40 or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return (
        parsed.tzinfo is not None
        and parsed.utcoffset().total_seconds() == 0
        and parsed <= datetime.now(timezone.utc)
    )


def audit_release_evidence(packet: object) -> ReleaseEvidenceAudit:
    """Audit shapes and consistency, never authenticity, safety or GO status."""
    if type(packet) is not dict:
        packet = {}
    release_sha = packet.get("release_sha")
    valid_sha = (
        type(release_sha) is str
        and fullmatch(r"[0-9a-f]{40}", release_sha) is not None
    )
    environment = packet.get("environment")
    valid_environment = _valid_identifier(environment)
    records = packet.get("gates")
    valid_records = type(records) is list and len(records) == len(GATE_IDS)
    entries = {}
    duplicates = set()
    if type(records) is list and len(records) <= 100:
        for entry in records:
            if type(entry) is not dict:
                continue
            key = entry.get("gate")
            if type(key) is str and key in GATE_IDS:
                if key in entries:
                    duplicates.add(key)
                else:
                    entries[key] = entry
    audits = []
    for gate in GATE_IDS:
        entry = entries.get(gate)
        reasons = []
        if not valid_records or gate in duplicates or entry is None:
            reasons.append("missing_or_duplicate_gate")
        if type(entry) is not dict or set(entry) != EXPECTED_KEYS:
            reasons.append("record_schema_invalid")
            entry = entry if type(entry) is dict else {}
        status = entry.get("status")
        if type(status) is not str or status not in RECORD_STATUSES:
            reasons.append("status_invalid")
            status = "NOT_TESTED"
        if status != "PASS":
            reasons.append("gate_not_passed")
        if not valid_sha or entry.get("release_sha") != release_sha:
            reasons.append("release_sha_mismatch")
        if not valid_environment or entry.get("environment") != environment:
            reasons.append("environment_mismatch")
        if not _valid_identifier(entry.get("owner")):
            reasons.append("owner_missing")
        if not _valid_identifier(entry.get("reviewer")):
            reasons.append("reviewer_missing")
        if not _valid_utc_timestamp(entry.get("tested_at")):
            reasons.append("timestamp_invalid")
        ref = entry.get("artifact_ref")
        if type(ref) is not str or fullmatch(_SAFE_REF, ref) is None:
            reasons.append("artifact_reference_missing")
        audits.append(GateAudit(
            gate=gate, recorded_status=status,
            evidence_complete=not reasons, blocking_reasons=tuple(reasons),
        ))
    complete = (
        type(packet) is dict
        and set(packet) == {"release_sha", "environment", "gates"}
        and valid_sha and valid_environment
        and valid_records and not duplicates
        and all(item.evidence_complete for item in audits)
    )
    return ReleaseEvidenceAudit(
        release_sha=release_sha if valid_sha else None,
        environment=environment if valid_environment else None,
        gates=tuple(audits),
        packet_complete=bool(complete),
        disposition="NO_GO",
        needs_independent_human_review=True,
        authorizes_release=False,
    )
