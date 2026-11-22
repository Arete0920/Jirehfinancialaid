# Jireh financial questionnaire — v1 field design candidate

**Status:** Design-only; the product owner approved the **seven sections**, not these
individual fields, defaults, financial calculations, retention rules, or live data
collection. **No migrations, APIs, financial storage, or deployed questionnaire.**

**Machine-readable candidate:** [questionnaire_v1_field_catalog.json](questionnaire_v1_field_catalog.json)
(7 sections, 31 proposed field paths, 10 explicit pending owner decisions).
The catalog is documentation metadata, **not** a validated JSON Schema, API payload
contract, user-facing questionnaire, or privacy certification.

## Proposed structure and source evidence

| Approved section | Candidate field-level content | Key design boundary |
| --- | --- | --- |
| Household members and contributors | Role, relationship, household residence, financial contributor indicator and optional school-scoped student link | A person/child link never grants access to another household's records |
| Income | Category, amount in USD cents, explicit start/end period, contributor, server-controlled source | Flow, not an as-of-date balance; gross/net, reporting year and category inclusion are undecided |
| Assets | Category, balance in USD cents, as-of date and ownership | Snapshot, not annual income; ownership, exemptions and limits undecided |
| Liabilities | Category, outstanding balance in cents, as-of date and responsible member | Snapshot; deductible categories and limits undecided |
| Recurring expenses | Category, amount in cents and explicit start/end period | Cash flow; deduction eligibility and monthly/annual conversion undecided |
| School-specific questions | Immutable question-definition identity/version and typed response | No arbitrary unvalidated JSON; same school and applicable year; school-global key uniqueness requires distinct DB constraint |
| Consent / attestation | Applicant decision, optional purpose-specific prior-year reuse opt-in, server actor ID and UTC timestamp | No implicit acceptance, cross-household consent, carry-forward or automatic verified status |

**Field-level values and choices are illustrative.** For example, the enum
`OTHER_APPROVED` is a marker for future owner-authorized categories, not permission
to send unrestricted text. Boolean `null` is **unanswered**, distinct from
`false`; unfilled money is **not** zero. The catalog explicitly leaves financial
bounds and currency treatment subject to policy approval.

## Verified source and improvements over CROWN

Reviewed authoritative CROWN SHA
`46b56609fe18360299b08eabaa8bccdffb356a0e`:
`backend/aid/models.py`, `backend/aid/services/profile_service.py`, and
`backend/aid/tests/test_aid_profile_modernization.py`. The existing profile
architecture includes member roles, line-item categories, source provenance,
verification status and explicit carry-forward consent. This is **reference
material**, not code imported into the standalone application.

Changes needed before reusing those concepts:

- Replace the legacy `annual_amount_cents` ambiguity for assets/liabilities
  with explicit flow periods versus snapshot dates.
- Authorize **each** person, question, application, school and year against the
  current explicit household access grant; separated households sharing a child
  must remain independent.
- Use immutable question versions; school-wide question uniqueness needs
  explicit semantics when no year is specified.
- Treat reuse as separate, purpose-specific, revocable consent with verified
  provenance. Copied information must return to unverified status.
- Audit safe metadata only, never answer contents or document identifiers.
- Preserve the existing production liveness-only routing until security and
  operational release gates are certified.

## Decisions required before any schema migration

The catalog tracks ten open decisions as `Q01` through `Q10`: reporting
years, money limits/periods, separated-parent contributor permissions,
household roster, required documents, allowable school questions, consent,
retention and incident handling, verification authority, and final signoff.

**Next work product after owner approval:** freeze the accepted field catalog
as a versioned immutable contract; implement a new isolated, test-only data
model and validation layer with disposable SQLite/PostgreSQL tenant-negative
tests. Real financial-data intake, final user routes, payment, assessment and
cloud resources require separately approved release gates.

## Test the design contract

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_questionnaire_field_catalog.py' -v
```

The contract tests enforce the approved seven-section set, path uniqueness,
candidate-only status, stock/flow separation, server timestamps, explicit
consent and unresolved policy gates. **Passing tests does not approve the
individual field choices or validate a submitted financial response.**
