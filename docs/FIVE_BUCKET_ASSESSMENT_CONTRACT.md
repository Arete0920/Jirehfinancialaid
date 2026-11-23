# Jireh five-bucket candidate assessment — synthetic arithmetic contract

**Status:** Test-only implementation for Issue #46. This is **not** an owner-approved mathematical aid formula, real financial assessment, school decision, committed award, payment or live data path.

The standalone pure-Python module src/jireh/financial_aid/assessment_contract.py is deliberately disconnected from Django, HTTP, CROWN, the ledger, payment providers and applicant data. Nothing in it assigns financial eligibility or produces a real award.

## Inputs and deterministic execution

A trusted, separately authorized caller must explicitly provide:

- Exact canonical UUID school and academic-year identifiers, plus a matching versioned CandidateAssessmentPolicy.
- Exactly five unique AidBucket rules (need, mission, marketing, merit, hardship) with independently approved, caller-supplied ratio numerator and denominator, rounding mode (FLOOR, HALF_UP, CEILING), maximum basis cents and recommendation cap cents.
- Exactly one nonnegative integer-cent synthetic basis per bucket and an explicit sum-of-recommendations review ceiling.

Rules use exact integer arithmetic and explicit rounding. No implicit 20%/5% CROWN rates, church participation attributes, household income derivation, currency conversion, missing-as-zero or inferred school policy are present.

The frozen, non-repr assessment contains five explainable lines with basis cents, ratio, rounding, uncapped and capped results and cap_applied. A total above the review ceiling fails closed, rather than silently trimming an award. All outputs are marked requires_school_authorization=True; no real decision is created.

**Critical trust boundary:** Matching UUIDs supplied to this function do not prove access. A future real service must independently derive school/year, applicant inputs and policy from authenticated school-bound records and a reviewed approval registry. Feed only fictional test data until those controls and production acceptance gates pass.

The original CROWN award formula in tests/legacy_crown remains historical regression evidence only. It is not imported into runtime, and no legacy MAS/faith/mission-weighted formula has been selected by this work. Five buckets are independent identifiers; school-directed award decisions remain separately authorized under Issue #47.

## Verification and follow-on

tests/test_assessment_contract.py verifies deterministic output, cap visibility, rounding boundaries, all-five-bucket completeness, exact money types, missing policy, over-ceiling failure, school/year mismatch, immutable results and sanitized errors. Python 3.12, Django 5.2, PostgreSQL 16, browser and SonarCloud checks are mandatory before merge.

Before live calculation: obtain the exact approved per-school methodology (basis definitions, eligibility, exemptions, ratios/caps, rounding, freshness, negative values, fairness/legal review); authenticate the policy version and actor, authorize scoped financial inputs, audit safe metadata and separately accept the school's award workflow. Production release remains NO-GO.
