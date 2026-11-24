# Jireh financial questionnaire — v1 field design candidate

**Status:** Field-list approved for development on November 22, 2026. The product owner approved the **seven sections and all 31 proposed field identifiers**. This approval is for standalone design, validation, and synthetic implementation only; it does **not** specify financial thresholds, final validation policy, consent language, retention periods, identity rules or release permission. **No migrations, APIs, financial storage, or deployed questionnaire are authorized by this catalog.**

**Machine-readable candidate:** [questionnaire_v1_field_catalog.json](questionnaire_v1_field_catalog.json)
(7 sections, 31 proposed field paths, 10 explicit pending owner decisions).
The catalog is documentation metadata, **not** a validated JSON Schema, API payload
contract, user-facing questionnaire, or privacy certification.

## Owner-approved field-list checkpoint (2026-11-22)

All 31 existing field identifiers in the seven approved sections have the catalog lifecycle `approved_for_development`. The catalog status is `FIELD_LIST_APPROVED_DESIGN_ONLY_NOT_COLLECTION`, with an explicit `field_list_approval` record. The field inventory and type names were not added to, removed from, or reinterpreted by this approval. The machine-readable version remains `0.1.0` because policy choices are not finalized.

The Q01–Q10 detailed policy decisions are tracked separately and still require specific values and controls; prior 'pending' text below documents those unresolved choices rather than revoking the field-list approval. This approval permits controlled synthetic design and tests, **not** storing actual family financial answers or activating real application submissions.

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

## Owner decision packet: Q01–Q03 (proposal only, 2026-11-22)

**Decision status: PENDING PRODUCT-OWNER AND PRIVACY APPROVAL.** These
recommendations do **not** update the 31-field candidate catalog or authorize
database migrations, answer storage, APIs, production data, financial scoring,
payments, deployment, or cross-household disclosure. The catalog's
`pending_owner_decisions` entries remain intentionally unresolved.

The recommendations below are based on the existing standalone school/year/
household boundaries, test-only validations, and the historical CROWN reference
at immutable revision `46b56609fe18360299b08eabaa8bccdffb356a0e`.
Historical CROWN uses `annual_amount_cents` for financial flows **and**
asset/liability snapshots; that is a source ambiguity to correct, not policy
authority to carry over.

### Q01 — reporting periods and academic-year identity

**Proposed v1 rule (not approved):** Keep the financial-aid *application* tied
to the school's explicitly identified academic year. Record income/expense
cash flows against a **separately and explicitly selected calendar reporting
year** with precise period start/end dates. The applicable tax/reporting year
must be chosen and approved for the school's aid cycle, never guessed from
the application's academic year or today's date. Asset and liability values
remain dated snapshots, not annualized income.

**Decision required:** Approve calendar-year reporting for annual income/
expenses, or select academic-year reporting or both as separately labeled
periods. Specify which reporting year(s) must be submitted for a given school
aid cycle, and whether current-year estimates are in or out of v1.

**Acceptance cases after approval:** A selected school aid year and its income
reporting year must be independently identifiable; a flow outside its approved
window must fail closed; an income record crossing a reporting boundary must
not be silently annualized or split; balance snapshots cannot be counted as
annual cash flow. No date window or year default is being configured here.

### Q02 — money, rounding, periods, and correction rules

**Proposed v1 safeguards (not approved):** Accept exact integer USD cents
only, with explicit per-field approved lower/upper bounds; preserve missing
as different from zero; reject booleans, floats, strings and implicit rounding.
Cash flows require start/end dates; assets/liabilities require an as-of date.
Do not automatically transform monthly amounts into annual figures. Treat
negative amounts or correction entries as **not accepted by default** unless
an individually approved category/policy explicitly permits them; retain
attributable correction history separately from the original submission.

**Decision required:** Specify allowable categories, field-specific minimum
and maximum cents, whether negative income/losses or correction values are
supported, permitted interval granularity, USD-only treatment, and explicit
rounding/conversion rules if any. No limits, exclusions, reporting periods or
auto-annualization may be inferred from synthetic test values.

**Acceptance cases after approval:** Rejected out-of-bounds and malformed
amounts return stable non-sensitive codes without logging values; empty vs
zero and stock vs flow remain distinct; no transaction is persisted until
authorization, approved field rules and privacy controls exist.

### Q03 — separated households, contributors and access

**Proposed v1 security posture (not approved for financial data):** An
existing explicit `HouseholdAccess` grant is bound to one household in one
school; the application and academic-year scope must be checked separately. Sharing a student does not imply access
to another household. Marking a person as a financial contributor never
grants them read, edit or consent authority. An adult must have their own
authenticated, active, explicit household authorization to submit an answer;
consent is purpose- and actor-specific and cannot cover another household by
assumption. Financial records of separated households remain independent.
School staff authorization continues to require explicit school/role grants.

**Decision required:** Approve the default of **no inter-household financial
visibility**; define which adult may submit or correct each contributor's
financial disclosures, whether household representatives may attest for
another adult, and whether a separately authorized process may combine
household financial results for **school-only** review. A shared child's link
must never become a permission or a cross-household data-copy mechanism.

**Acceptance cases after approval:** Synthetic tests must exercise two
households sharing a student, each with distinct grants/answers, revoked and
expired permissions, unauthorized contributor IDs, cross-school/year requests,
CSRF failures and forged headers. Neither household may read the other's
answers or infer them from error responses. No cross-household assessment
aggregation is authorized by this proposal.

### Explicit approval record required before development

The owner can record an approval or requested modification for **each**
decision in [issue 43](https://github.com/Arete0920/Jirehfinancialaid/issues/43).
A response of "proceed" to general development is **not** equivalent to
accepting unreviewed values or collection rules. Owner-reviewed Q01–Q03
policy remains a subset of the wider Q01–Q10 gate: household roster (Q04),
documentation (Q05), school-defined questions (Q06), consent (Q07), retention/security (Q08),
verification (Q09), and final sign-off (Q10) remain unresolved.

After approval, freeze a separately versioned accepted policy/field contract
and add disposable synthetic tests before considering migrations. For now,
keep all product/production collection paths disabled.

## Q04-Q10 interim safeguards — owner-authorized design baseline

**Status: DESIGN GUARDRAILS ONLY; collection and production remain NO-GO.**
The product owner authorized proceeding with the remaining questionnaire
policy decisions. The following conservative defaults are recorded for
engineering design and negative tests, not as permission to collect real
financial data or as certification of legal/privacy compliance. Specific
unresolved implementation choices remain in the machine-readable catalog's
`policy_safety_baselines.decisions[*].outstanding_authorizations` entries.
All 31 field definitions remain candidates; no field is approved for live
collection. Existing Q01-Q03 academic-year, financial-value, and independent
household safeguards continue to apply.

### Q04 — Household roster

Reuse an already-authorized standalone Jireh household/student relationship
rather than requiring unnecessary duplicate identity entries. A shared child,
residence, family relationship or financial contributor flag must never grant
access to another household's data. Dependent counting cannot be inferred
from the count of linked students or from custodial status.

**Still requires approval:** Minimum adult identity fields; which people
qualify as dependents and contributors; permitted corrections; and any
identity-proofing requirements before the questionnaire is released.

### Q05 — Financial documents

Document upload stays disabled until there is approved encrypted storage,
file-type/size allowlists, malware inspection, exact household/application
authorization and retention/deletion behavior. No direct public object links,
credentials or document contents may appear in logs, audit records or exports.
Do not automatically require tax returns, payroll records or bank statements
from every family without an approved requirement for the specific question.

**Still requires approval:** Required evidence by question, file limits,
storage provider and encryption keys, download/revocation controls,
backup expiry and document retention. Track technical implementation in
[issue #44](https://github.com/Arete0920/Jirehfinancialaid/issues/44).

### Q06 — School-specific questions

Schools cannot publish new custom questions until question topics, data
types, conditional logic, length limits and publisher roles have been vetted.
Definitions must be scoped to school and applicable year, with immutable
versions for existing answers and no unrestricted JSON/free-form sensitive
data. Sensitive questions, including those involving affiliation or
demographics, require separate fairness and privacy review.

**Still requires approval:** Permitted question taxonomy, field bounds,
school publisher authority and changes to existing questionnaire versions.

### Q07 — Consent and prior-year reuse

Accuracy attestation and optional prior-year reuse are separate affirmative
acts. Neither is preselected. Reuse cannot occur automatically; any eventual
consent record must bind explicit purpose, disclosure version, authenticated
and authorized actor, school/household/year, and server-generated timestamp.
Consent by one household never authorizes access to another household.
Withdrawal must stop unauthorized future reuse, but does not automatically
erase data subject to a separately accepted retention obligation.

**Still requires approval:** Actual consent language, adults authorized to
attest, withdrawal effects and processes, duration and re-verification.
Final application submission remains [issue #45](https://github.com/Arete0920/Jirehfinancialaid/issues/45).

### Q08 — Retention, security and incident response

Live financial intake remains disabled until an authorized data-class
retention and deletion schedule exists. Distinguish drafts, submitted
answers, supporting files, consent evidence, audit events, exports, backups
and legal holds. Require encryption in transit/at rest, scoped exports,
metadata-only audit, reviewed secrets and keys, incident response and
tested recovery. No blanket retention period or universal legal
applicability is inferred.

**Still requires approval:** Data-class durations, statutory/contractual
grounds by school and jurisdiction, key/hosting architecture, named
responders, breach processes, deletion SLA, backups and holds. These remain
blocked by [security issue #48](https://github.com/Arete0920/Jirehfinancialaid/issues/48).

### Q09 — Verification

An applicant assertion is not independently verified. Uploaded evidence
and financial formulas never automatically verify a record. A reviewer
must have an active, explicit authorization for the correct school and
documented evidence/provenance. A changed answer invalidates the affected
verification; log status changes and actor metadata, not raw amounts.

**Still requires approval:** Verification evidence standards, state
transitions, any additional reviewer roles, and re-review procedures.
Existing SchoolStaffAccess recognizes AID_DIRECTOR; this design does not
introduce or authorize another staff role.

### Q10 — Final field, privacy and release approvals

Freeze an owner-approved, versioned field/policy contract before migrations.
Record authorized product-owner or integration-manager signoff, separate
privacy/security review, and final financial methodology approval. Live
operation additionally requires every exact-release production acceptance
gate to PASS and an explicit environment-specific GO decision. This
Q04-Q10 design review is **not** that decision.

**Still requires approval:** Exact approved field list, reporting-year
mapping, amount bounds, household permissions, consent and retention rules,
data-protection design, scoring methodology, operational evidence and
production release authorization.

**Engineering follow-on:** Use synthetic tests to enforce scope/consent and
disabled-capability defaults while Q01-Q10 still contain open policy values.
Do not create persistent financial-answer models, live questionnaires,
upload flows or production endpoints from this design metadata.

---

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
