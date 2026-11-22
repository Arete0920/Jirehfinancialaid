# CROWN financial-aid reuse register — first executable checkpoint

**Status:** Historical reference preserved; **NO standalone award engine approved.**
**Source repository:** [Arete0920/Crown-CSMS](https://github.com/Arete0920/Crown-CSMS), immutable SHA `46b56609fe18360299b08eabaa8bccdffb356a0e`.
**Destination baseline:** [Arete0920/Jirehfinancialaid](https://github.com/Arete0920/Jirehfinancialaid), protected main `5d9162a3bfa3917512a12fee8b74f6c050ce0a56`.

## Executable historical parity evidence

- Source: `backend/aid/services/award_engine.py` → `tests/legacy_crown/award_engine.py`.
- Source: `backend/aid/tests/test_aid_engine.py` → `tests/test_crown_award_parity.py`.
- **Only test import changes:** Django `TestCase` becomes standard-library `unittest.TestCase`; the imported engine location points to the test-only reference package. This avoids requiring application models or running a database for parity checks.
- The historical engine's calculation functions and old test assertions are otherwise retained. No Jireh runtime module imports this reference. Run with the existing Python contract job: `PYTHONPATH=src python -m unittest discover -s tests -v`.
- Verify the exact candidate GitHub SHA and full CI results before asserting successful parity. The historical test suite does **not** establish the correctness, appropriateness, or safety of the methodology.

## Reuse decision matrix (initial read-only triage)

| CROWN asset | Initial finding | Standalone disposition |
| --- | --- | --- |
| `backend/aid/services/award_engine.py` | Pure calculation; deterministic outputs for given inputs; reads no CROWN ORM or ledger | **Preserved as test-only reference.** Candidate for a separately reviewed, policy-driven standalone implementation |
| `backend/aid/tests/test_aid_engine.py` | Existing boundary, numeric and recommendation tests | **Portable tests captured** with import changes only |
| `backend/aid/services/profile_service.py` | Current-year financial line items, provenance, validation and prior-year consent; direct `aid.models` and Django dependencies | **Adapt concepts**, not wholesale code |
| `backend/aid/models.py` | School/year scoped applications, review, award budget, profiles, household member and questions | **Map schema and policies**, preserving independently verified standalone household grants and UUID tenants |
| `backend/financial_aid/need_index.py` | Separate weighted need-index approach, with CROWN `TuitionPlan` dependency and fixed fallback values | **Do not merge formulas** until owner selects a method |
| `backend/financial_aid/workflows.py` | Application processing depends on `signals`, `core`, Solomon, Crown Compass and other CROWN systems | **Do not port directly** |
| `backend/aid/services/ledger_bridge.py` | Uses CROWN `core`, `households`, `ledger` and student-account posting | **Do not port directly**; reuse tested idempotency / reversal requirements for future optional adapters |
| `backend/aid/tests/test_aid_award_invariants.py` | Ledger sign, double posting, reversal, audit tests | **Retain as future acceptance requirements**; not standalone payment approval |
| `backend/aid/services/award_engine.py` mission factors | Policy weights and adjustments tied to faith/church participation; potential fairness and legal issues | **Do not activate** without product-owner policy and legal/privacy review |

## Source-level concerns identified before porting

1. The legacy need computation applies fixed rates of 20% to income above the floor and 5% to net assets. These assumptions have not been commercially or legally accepted for standalone Jireh.
2. The legacy engine uses binary floating-point multipliers and `int(...)` truncation for money; a production calculator should adopt explicit integer/decimal rounding and range contracts.
3. The legacy mission modifier can lower the recommended award below the minimum configured percentage, according to its historical tests; whether this behavior is acceptable is an owner decision.
4. The `backend/financial_aid/need_index.py` pathway instead assigns special weights and defaults to income, dependents, hardship and aid history. **Do not silently combine** these two systems.
5. Financial aid need and school-approved awards must remain distinct; no recommendation may post to accounts, authorize payment, or create a final decision without school-scoped review.
6. Existing Jireh `AidApplication` has only DRAFT data, no financial input schema, policy model, assessment service, or production customer APIs; importing historical tests must not change that.

## Next implementation gate

Product owner must approve field taxonomy, need methodology/constraints, consent and data-handling rules. Only then prepare a separate bounded production implementation for issues [#43](https://github.com/Arete0920/Jirehfinancialaid/issues/43) and [#46](https://github.com/Arete0920/Jirehfinancialaid/issues/46), with CROWN parity tests and **new independent negative tests**. Preserve CROWN as the authoritative legacy source for any further reconciliation. Do not enable production, migrations, real data or payments through this register.

## Phase 2 — annual financial questionnaire reuse assessment (2026-11-22)

**Status: REQUIREMENTS PROPOSAL, not approved code or a database migration.**
Sources were read from the authoritative CROWN commit `46b56609fe18360299b08eabaa8bccdffb356a0e`:
`backend/aid/models.py` (lines 629–856),
`backend/aid/services/profile_service.py`, and
`backend/aid/tests/test_aid_profile_modernization.py`.
Standalone Jireh protected baseline: `4693bfa0c11bcf275706bbfbb56b258c1a0d943d`.

### Verified components and disposition

| Historical capability | Existing CROWN behavior | Standalone decision |
| --- | --- | --- |
| Annual financial profile | Per school, academic year and family, with status and confirmation fields | **Reuse the lifecycle concept.** Map to Jireh's already-protected school/academic-year/**household** application; do not copy CROWN `Family` foreign keys |
| Household members | Adult, student, dependent and contributor roles, names, relationship and financial responsibility | **Candidate, requires approval.** Household membership and financial responsibility are not authorizations; separated households must never inherit each other's access through a shared student |
| Financial line items | Income, asset, liability and expense categories; label, subcategory, integer cents, provenance, verification metadata | **Candidate, requires amount-period redesign.** Income/expenses are flows; assets/liabilities are generally balances as of a date |
| Financial totals | Summation of per-category amounts, including four summary outputs | Reuse only with separately approved definitions, validation, freshness and explicitly chosen rounding/period treatment |
| Question definitions | School, nullable academic year, question key, typed responses, required/active, order, JSON options and conditions | **Candidate, requires versioned schema.** School/year scope, conditions, input limits and response-type validation must be accepted before APIs |
| Question responses | One JSON response per application/question pair | **Do not copy as-is.** Validate question belongs to same school and applicable year, and bind responses to immutable question versions |
| Prior-year carry-forward | Requires `consent_to_reuse`; copies household members and financial values; resets verification to unverified and new status DRAFT | Reuse the consent-and-unverified principle only. Must independently validate source/destination scope, renewed consent and provenance; do not implement auto-carry-forward yet |
| Review signals | Flags missing confirmation, unverified items, missing documentation, financial changes and related needs for review | Reuse explainable *human review* signals when there is an approved questionnaire and document policy; never equate signals with eligibility or an automatic award |
| CROWN finance / student ledger | Direct integration with CROWN accounting and student accounts | No direct imports or coupling. Optional future adapter only, separately approved and tested |

### Identified gaps requiring correction, not transplantation

1. **Amount units are ambiguous.** CROWN `AidFinancialLineItem.annual_amount_cents` is used for all four categories (source lines 740–777), including asset and liability balances; `totals()` carries that name through summation (lines 684–701). A new model must explicitly distinguish annual/monthly *flows* from point-in-time *balances*, with a date/period and a consistent cents contract. No conversion rate or category-specific treatment is approved yet.
2. **School/year identity must be checked at every write.** CROWN `carry_forward_profile()` uses the previous profile's school and family with a supplied year, but does not explicitly compare destination academic year's school against the source profile before copy. Standalone services and PostgreSQL integrity constraints must reject mismatches even from direct writes; CROWN's existing tests do not establish this boundary.
3. **Nullable year requires deliberate uniqueness.** CROWN `AidQuestion` permits `academic_year=NULL` while declaring uniqueness on `(school, academic_year, key)`. Default PostgreSQL NULL-distinct semantics can permit duplicate school-global keys. Proposed standalone schema should define either year-required questions or separate partial unique constraints for global vs year-specific definitions.
4. **Responses require their own authorization.** CROWN `AidResponse` links application and question but has no explicit school/year fields or cross-table school matching at the model declaration (source lines 842–851). Standalone response reads/writes must authorize the exact household and validate question scope regardless of a supplied question ID or forged school header.
5. **Consent is not a portable blanket grant.** Prior-year consent for one school, household and purpose does not authorize another school's use or access by a different household sharing a child. Any carry-forward must reset verification and require explicit source/destination authorization and audited, purpose-specific consent decisions. The exact annual renewal policy is **not approved**.
6. **Current Jireh audit is limited.** Its `AidAuditEvent` currently supports draft creation and child selection only. Future financial-answer edits require metadata-only audit events with actor, school, application, question/version and action; no raw income, documents, answer text or access credentials in audit payloads.
7. **Question versioning and data minimization are not defined.** A school updating a question prompt or options must not silently reinterpret a family's prior answer. Storage, query, logging, export, and retention policies must be accepted before real answers are collected.

### Candidate v1 questionnaire decisions — **NOT YET APPROVED**

These are candidate *sections*, not a license to create columns or collect information:

| Candidate section | Proposed minimum purpose | Decision still required |
| --- | --- | --- |
| Household and contributors | Identify which adults contribute and which students/dependents are included | Household size rules, custody/separated-parent treatment, financial responsibility and whether names must be duplicated |
| Annual income | Household or contributor income for an identified reporting period | Tax year vs academic year, gross/net treatment, categories, zero vs unanswered, annualization, documentation and verification |
| Assets | Balance/valuation snapshot at a stated date | Types of assets, treatment/exemptions, ownership, valuation date, negative values and whether household or contributor level |
| Liabilities | Outstanding balances at a stated date | Which liabilities qualify, deductions, supporting evidence, negative values and reconciliation |
| Recurring expenses | Cash outflows over an explicit period | Which expenses count, monthly vs annual entry and permitted adjustments |
| School-specific questions | Optional versioned prompts associated with the school and applicable year | Approved field types, requiredness rules, conditional visibility, limits, sensitive categories, school review and version history |
| Reuse consent and attestation | Meaningful applicant consent, confirmation and provenance | Year-to-year reuse conditions, withdrawal, data-retention schedule, consent actor and timestamp, whether an adult's consent covers another adult |

**No faith/church affiliation inputs, MAS factors, financial coefficients, scoring,
eligibility, demographic attributes or tax-document requirements are approved
by this document.** They are distinct decisions with potential legal, privacy
and fairness implications.

### Acceptance contract for issue #43 (after written owner approval)

1. Every profile, question, response and contributor is resolved through an authenticated, current, explicit `HouseholdAccess` and exact school/household/academic-year scope; an unrelated school/household sharing a child receives no data.
2. GET/POST/PATCH are absent from production routes until privacy, real authentication, authorization, secure storage, and all relevant security gates pass.
3. A draft can be saved/resumed/corrected idempotently without treating missing values as zero, silently changing answer types, or implicitly submitting or verifying.
4. Values use an explicitly approved money type, period, bounds and validation. Financial answers never enter exception traces, metrics labels, audit details or GitHub test fixtures.
5. Revoking a grant immediately denies authenticated sessions; CSRF, forged headers, mismatched question scope and cross-school application IDs are rejected without side effects.
6. School question definitions are versioned/frozen for existing responses, with both application-school integrity and question-year integrity checked at persistence and PostgreSQL boundaries.
7. Carry-forward (when separately approved) is explicit, consent-bound, same-household/school (unless a later separate approved mechanism), independently reauthorized and *unverified* for the new year.
8. Disposable synthetic SQLite and PostgreSQL suites cover boundary, correction, permission, versioning, stale/invalid amounts, revocation and concurrency tests. Real-person data stays outside CI and repositories.
9. Define retention, access logging, storage encryption, exports, school administrator scope, secrets and incident response policies with issue #48 before any live financial data is accepted.

### Approval gate (product owner / privacy review)

For issue [#43](https://github.com/Arete0920/Jirehfinancialaid/issues/43),
the minimum explicit authorization is: **(a)** which candidate sections
are in v1, **(b)** reporting period and amount semantics, **(c)** separated-parent
financial responsibility and participant permissions, **(d)** source-document,
reuse-consent and retention policy, and **(e)** whether custom school questions
are allowed in v1 and which types. If any is unresolved, advance test-only
acceptance and review, not real-data collection or migrations.

This assessment is not a completed security assessment, legal opinion,
approved user questionnaire, or authorization to implement CROWN scoring.
