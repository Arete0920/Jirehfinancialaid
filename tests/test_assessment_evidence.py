"""Acceptance for versioned fictional assessment evidence."""

from dataclasses import replace
from unittest import TestCase
from uuid import UUID, uuid4

from jireh.financial_aid.assessment_contract import CandidateAssessmentError
from jireh.financial_aid.buckets import AidBucket
from test_assessment_contract import SCHOOL_A, SCHOOL_B, YEAR_A, YEAR_B, policy

from jireh.financial_aid.assessment_evidence import (
    EvidenceState, FictionalAssessmentEvidence, FictionalBucketEvidence,
    assess_fictional_evidence,
)


class FictionalAssessmentEvidenceTests(TestCase):
    def setUp(self):
        self.application_id = str(uuid4())
        self.snapshot = FictionalAssessmentEvidence(
            school_id=SCHOOL_A, academic_year_id=YEAR_A, application_id=self.application_id,
            version="fictional-evidence-v1", revision=3,
            buckets=tuple(FictionalBucketEvidence(
                bucket=bucket, state=EvidenceState.READY, source_id=str(uuid4()),
                source_revision=3, basis_cents=basis,
            ) for bucket, basis in zip(AidBucket, (0, 4, 8, 12, 16))),
        )

    def assess(self, snapshot=None, **overrides):
        inputs = {
            "snapshot": snapshot or self.snapshot, "policy": policy(),
            "school_id": SCHOOL_A, "academic_year_id": YEAR_A,
            "application_id": self.application_id, "expected_version": "fictional-evidence-v1",
            "expected_revision": 3,
        }
        return assess_fictional_evidence(**(inputs | overrides))

    def test_ready_evidence_uses_existing_arithmetic_for_all_buckets(self):
        result = self.assess()
        self.assertEqual(result, self.assess())
        self.assertEqual(str(result.application_id), self.application_id)
        self.assertEqual((result.evidence_version, result.evidence_revision), ("fictional-evidence-v1", 3))
        self.assertEqual(result.policy_version, "fictional-v1")
        self.assertEqual(tuple(signal.bucket for signal in result.signals), tuple(AidBucket))
        self.assertEqual({signal.state for signal in result.signals}, {EvidenceState.READY})
        self.assertEqual([line.recommendation_cents for line in result.assessment.lines], [0, 1, 2, 3, 4])
        self.assertEqual(result.assessment.total_recommendation_cents, 10)
        self.assertTrue(result.assessment.requires_school_authorization)

    def test_unavailable_or_ineligible_evidence_never_becomes_a_zero_recommendation(self):
        ready, missing, stale, unverified, ineligible = self.snapshot.buckets
        incomplete = replace(self.snapshot, buckets=(
            ready,
            replace(missing, state=EvidenceState.MISSING, source_id=None,
                    source_revision=None, basis_cents=None),
            replace(stale, source_revision=2),
            replace(unverified, state=EvidenceState.UNVERIFIED, basis_cents=None),
            replace(ineligible, state=EvidenceState.INELIGIBLE, basis_cents=None),
        ))
        result = self.assess(incomplete)
        self.assertIsNone(result.assessment)
        self.assertEqual([signal.state for signal in result.signals], [
            EvidenceState.READY, EvidenceState.MISSING, EvidenceState.STALE,
            EvidenceState.UNVERIFIED, EvidenceState.INELIGIBLE,
        ])
        stale_signal = result.signals[2]
        self.assertEqual(stale_signal.source_id, UUID(stale.source_id))
        self.assertEqual(stale_signal.source_revision, 2)
        self.assertFalse(hasattr(stale_signal, "basis_cents"))

    def test_scope_policy_and_current_revision_are_bound_before_assessment(self):
        for inputs in (
            {"school_id": SCHOOL_B, "policy": policy(school_id=SCHOOL_B)},
            {"academic_year_id": YEAR_B, "policy": policy(academic_year_id=YEAR_B)},
            {"application_id": str(uuid4())},
        ):
            with self.subTest(inputs=inputs):
                with self.assertRaisesRegex(CandidateAssessmentError, "^candidate_evidence_scope_mismatch$"):
                    self.assess(**inputs)
        with self.assertRaisesRegex(CandidateAssessmentError, "^candidate_evidence_revision_mismatch$"):
            self.assess(expected_revision=4)
        with self.assertRaisesRegex(CandidateAssessmentError, "^candidate_evidence_version_mismatch$"):
            self.assess(replace(self.snapshot, version="fictional-evidence-v0"))
        with self.assertRaisesRegex(CandidateAssessmentError, "^candidate_policy_scope_mismatch$"):
            self.assess(policy=policy(school_id=SCHOOL_B))

    def test_invalid_or_ambiguous_evidence_fails_closed(self):
        first, *other = self.snapshot.buckets
        for row in (
            replace(first, basis_cents=True),
            replace(first, source_revision=4),
            replace(first, source_revision=True),
            replace(first, source_id=str(UUID(int=0))),
            replace(first, state=EvidenceState.MISSING),
            replace(first, state=EvidenceState.UNVERIFIED),
            replace(first, state=EvidenceState.STALE),
            replace(first, bucket=other[0].bucket),
        ):
            with self.subTest(row=row):
                with self.assertRaises(CandidateAssessmentError):
                    self.assess(replace(self.snapshot, buckets=(row, *other)))
        with self.assertRaisesRegex(CandidateAssessmentError, "^candidate_evidence_version_invalid$"):
            self.assess(replace(self.snapshot, version="fictional evidence"))

    def test_incomplete_evidence_does_not_mask_invalid_current_amounts_or_policy(self):
        first, second, *rest = self.snapshot.buckets
        first = replace(first, basis_cents=1_000_001)
        second = replace(second, state=EvidenceState.MISSING, source_id=None,
                         source_revision=None, basis_cents=None)
        evidence = replace(self.snapshot, buckets=(first, second, *rest))
        with self.assertRaisesRegex(CandidateAssessmentError, "^candidate_basis_exceeds_ceiling$"):
            self.assess(evidence)
        with self.assertRaisesRegex(CandidateAssessmentError, "^candidate_policy_bucket_set_invalid$"):
            self.assess(evidence, policy=replace(policy(), bucket_rules=()))
