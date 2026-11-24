"""Offline release evidence audit: no gate can authorize production."""
import copy
import unittest
from datetime import datetime, timezone

from jireh.runtime.release_evidence import GATE_IDS, audit_release_evidence


SHA = "a" * 40
ENV = "jireh-acceptance"
STAMP = "2026-11-22T20:00:00Z"


def packet():
    return {
        "release_sha": SHA,
        "environment": ENV,
        "gates": [
            {
                "gate": gate, "status": "PASS",
                "release_sha": SHA, "environment": ENV,
                "owner": "reviewer-owner", "reviewer": "security-reviewer",
                "tested_at": STAMP,
                "artifact_ref": "github://evidence/synthetic-" + gate,
            }
            for gate in GATE_IDS
        ],
    }


class ReleaseEvidenceTests(unittest.TestCase):
    def blocked(self, record):
        result = audit_release_evidence(record)
        self.assertEqual(result.disposition, "NO_GO")
        self.assertFalse(result.authorizes_release)
        self.assertTrue(result.needs_independent_human_review)
        self.assertEqual(tuple(x.gate for x in result.gates), GATE_IDS)
        return result

    def test_even_perfectly_shaped_packet_never_authorizes_release(self):
        audit = self.blocked(packet())
        self.assertTrue(audit.packet_complete)
        self.assertTrue(all(g.evidence_complete for g in audit.gates))

    def test_empty_or_malformed_packet_blocks_all_gates(self):
        for value in (None, {}, "", [], True, {"gates": []}):
            with self.subTest(value=value):
                audit = self.blocked(value)
                self.assertFalse(audit.packet_complete)
                self.assertTrue(any(not gate.evidence_complete for gate in audit.gates))

    def test_missing_duplicate_unknown_and_extra_gates_are_rejected(self):
        for edit in (
            lambda p: p["gates"].pop(),
            lambda p: p["gates"].append(copy.deepcopy(p["gates"][0])),
            lambda p: p["gates"][0].update(gate="UNKNOWN"),
            lambda p: p["gates"].append({"gate": "UNKNOWN"}),
            lambda p: p.update(extra="ignored"),
        ):
            value = packet()
            edit(value)
            self.assertFalse(self.blocked(value).packet_complete)

    def test_failed_or_unverified_status_blocks(self):
        for status in ("NOT_TESTED", "FAILED", "PASS ", None, {}, [], True):
            with self.subTest(status=status):
                value = packet()
                value["gates"][0]["status"] = status
                audit = self.blocked(value)
                self.assertFalse(audit.packet_complete)
                self.assertIn("gate_not_passed", audit.gates[0].blocking_reasons)

    def test_exact_sha_and_environment_scope_required(self):
        for change in (
            lambda p: p.update(release_sha="short"),
            lambda p: p["gates"][0].update(release_sha="b" * 40),
            lambda p: p.update(environment="bad env"),
            lambda p: p["gates"][0].update(environment="other-environment"),
        ):
            value = packet()
            change(value)
            self.assertFalse(self.blocked(value).packet_complete)

    def test_missing_reviewers_artifact_and_timestamp_block(self):
        for key, bad in (
            ("owner", ""), ("owner", None), ("reviewer", None),
            ("artifact_ref", ""), ("artifact_ref", "secret value"),
            ("tested_at", ""), ("tested_at", "2026-11-22"),
            ("tested_at", "2099-01-01T00:00:00Z"),
        ):
            with self.subTest(key=key, bad=bad):
                value = packet()
                value["gates"][3][key] = bad
                self.assertFalse(self.blocked(value).packet_complete)

    def test_unknown_schema_or_duplicate_keys_via_record_rejected(self):
        value = packet()
        value["gates"][0]["financial_data"] = "should never be recorded"
        audit = self.blocked(value)
        self.assertFalse(audit.packet_complete)
        self.assertIn("record_schema_invalid", audit.gates[0].blocking_reasons)

    def test_no_underlying_artifacts_or_approval_claims_verified(self):
        # This is deliberately only a SHAPE audit, not a signature or artifact
        # content proof. The same invariant holds for a plausible forged packet.
        plausible = packet()
        plausible["gates"][0]["artifact_ref"] = "github://fake-evidence"
        audit = self.blocked(plausible)
        self.assertTrue(audit.packet_complete)
        self.assertFalse(audit.authorizes_release)


if __name__ == "__main__":
    unittest.main()
