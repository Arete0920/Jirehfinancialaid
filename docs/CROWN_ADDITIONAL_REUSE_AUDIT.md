# CROWN → standalone Jireh: additional reuse audit (UI, reports, workflows, privacy)

**Verified snapshot:** CROWN `Arete0920/Crown-CSMS` protected main
`46b56609fe18360299b08eabaa8bccdffb356a0e`; standalone Jireh
protected main `7d2c84a0044d70c70e2d7a7e2771760c3494a9b7`.

**Assessment scope:** the two complete Git trees and the targeted financial-aid
frontend, backend reporting, export, access-control and test sources listed below.
This is a **file-inventory and selected source review, not a proof every file or
15 months of historical branches was examined**. Files on earlier branches or
deleted from current main are not inventoried here.

**Current action:** preserve only one pure, database-independent CROWN reporting
aggregation function in `tests/legacy_crown/financial_aid_reporting.py`, with
nine independently written standard-library test methods
(`tests/test_crown_reporting_parity.py`). The functions validate school/year
scope, record counts, award face value, invalid linkages and ledger conflicts.
**No reporting endpoint or dashboard is enabled.**

## Newly identified reusable work (not in the original CROWN reuse register)

| Area and CROWN source (all paths relative to CROWN SHA above) | Observed implementation / evidence | Safe reuse judgment | Standalone target |
| --- | --- | --- | --- |
| **Canonical financial-aid reporting** `backend/crown_api/dashboards/financial_aid_live.py` | Pure `summarize_financial_aid_rows` checks cross-school family/student/award associations, status, accepted award/ledger links and record-vs-household count semantics. Its second function queries CROWN ORM. | **Preserved pure historical reference only**; do not copy CROWN ORM, status mappings, ledger posting or live API. Existing tests: `backend/crown_api/dashboards/tests/test_financial_aid_live_aggregation.py` and `test_financial_aid_live_query_contract.py`. | #47 school reporting; #48 production controls |
| **Financial-aid reporting dashboard** `frontend/dashboards/src/pages/FinancialAidDashboard.jsx` and `.../financialAidDashboard.js` | Dashboard shell/pattern and operational KPI cards, but old config contains **illustrative application counts, disbursement amounts, compliance status and actions**. `FinancialAidDashboard.dataTruth.test.jsx` suppresses illustrative values; `FinancialAidDashboard.runtimeDataTruth.test.jsx` asserts error/loading must NOT show fallback metrics. | **Reuse UX and no-fake-data acceptance rules, not old values, route, synthetic priorities, or CROWN UI framework.** No Jireh reporting UI has been established. | #47 reporting and UX acceptance |
| **Staff case review and award workflow** `frontend/dashboards/src/pages/JirehAidDecisionsPage.jsx` and `...retry.test.jsx` | Role-aware case selection, student validation, offer/review and explicit human approval. Tests cover ambiguous POST outcome and no blind retry. Uses CROWN auth, `CrownLayout`, CROWN dashboard/ledger. | **Adapt interaction sequence and negative acceptance tests** after standalone review/award policy approval; do not transplant React component or award-posting behavior. | #47 review and audit |
| **Family experience** `frontend/dashboards/src/pages/ParentFinancialAidPreparationPage.jsx` and `...test.jsx` | Family progress, selected-child workflow, consent/confirmation, saved server readback, role-aware shell. Current implementation explicitly fictional/sandbox. | **Adapt accessible patterns and canonical readback requirement**, not demo routes or local CROWN identity/session storage. | #43/#45 form experience |
| **Financial-aid wizard** `frontend/dashboards/src/pages/FinancialAidWizard.jsx`, `financial_aid_wizard/Step1Year.jsx` through `Step6Verify.jsx` | Six-stage setup: year, buckets, awards, preview, commit, verify. `Step3Awards.test.jsx` denies partial entries and missing amount/application. The workflow is **officer/admin award staging**, not the household questionnaire. | **Adapt preview/confirmation, partial-row validation and verified write patterns**; do not reuse as a family intake wizard or directly copy CROWN backend sessions. | #45/#47 |
| **Presentation primitives** `frontend/dashboards/src/components/crown-dashboard/CrownDashboardMetricCard.jsx`, `CrownDashboardDataTruthStatus.jsx`, `CrownDashboardEmptyState.jsx` | KPI cards, visible live/fallback status, and empty/error UI; imported launch components, theme and libraries. | **Reimplement small standalone Jireh primitives later**, not direct import. Provide accessible error, no-records, busy, needs-reconciliation, and verified states. | UI acceptance for #42/#43/#47 |
| **Export controls** `backend/crown_api/exports/permissions.py`, `backend/crown_api/exports/tests/test_exports_financial_csv.py` and `test_export_tenant_boundaries.py` | Export requires authenticated authorized finance actors and school scope; example CSV tests primarily finance/ledger, **not a finished standalone aid export**. | **Reuse security acceptance only**, not broad CSV or financial-data export. Privacy minimization and approved fields required before export code. | #47/#48 |
| **Sensitive-field access boundaries** `backend/aid/tests/test_aid_sensitive_access.py` | Parent vs officer read boundaries; forged student/year denial; restricted financial data not leaked via family status. CROWN role + family models. | **Translate into standalone tenant/privacy negative tests**, with explicit household access and separated-parent cross-grant denial. | #43/#47 |
| **Retry and ambiguous-outcome checks** `backend/aid/tests/test_recommend_award_retry_guard.py`, `frontend/dashboards/src/pages/JirehAidDecisionsPage.retry.test.jsx` | CROWN verifies 409 conflicting offer retries, concurrent offers, no duplicate financial mutation when prior POST may have committed. | **Reuse constraints and failure-mode tests**; no writes or ledger posting until standalone lifecycle and transaction design reviewed. | #45/#47 |
| **Hosted synthetic E2E flows** `frontend/dashboards/tests/e2e/hosted-jireh-local-contract.spec.ts` | Synthetic invited family and staff role journeys, school denial, canonical GET readback and local CI-only gate. | **Reuse scenario assertions only**; current standalone local Chromium demo is different and remains non-production. | #42/#49 |
| **CROWN API contract** `docs/api/FINANCIAL_AID_API_CONTRACT.md` | School-scoped reporting/summary/drilldown interface with example status and amount representations. Uses CROWN headers and APIs. | **Reference for reporting field names only**; standalone version needs new identity scopes and must separate award commitment, accepted face value, and true cash movement. | #47 |

## Key exclusions / integrity hazards

1. **No fake production dashboards.** Existing CROWN
   `frontend/dashboards/src/config/dashboardTemplates/financialAidDashboard.js`
   has hard-coded sample counts, dollars, dates, alerts and claims (including
   disbursements and compliance). Do **not** port any numerical samples or
   claims into Jireh's operational UI. Empty verified dataset = truthful zero;
   unavailable/unauthorized/unverified data = explicit unknown/error, not zero.
2. **Accepted awards are not disbursements.** The reference reporting function
   counts `accepted_award_face_value_cents` separately and records unposted
   accepted awards. The legacy CROWN ledger is **not** standalone Jireh's
   payment processor or tuition accounting system. No cash posting or
   CompuWerx activation is implied by historical ledger validation.
3. **Never count students as household applications.** An annual household
   application may cover multiple students; displayed metrics must distinguish
   submitted applications, distinct households, selected children, award
   *records*, award face value and verified cash movement.
4. **Never use CROWN auth/session identifiers for standalone Jireh.** The old
   React pages reference `getSelectedSchoolId`, `getAccessToken`, Crown
   context-change events and CROWN backend paths. New runtime controls
   must use standalone Jireh's independently reviewed authenticated grants
   and server authorization. Client-side filtering is not a security barrier.
5. **No direct dashboard/React dependencies.** The current standalone project
   has no production frontend framework/screen collection comparable to
   CROWN's React/Vite dashboard. Copying CROWN UI would import theme, API,
   auth and shell dependencies, expand runtime/maintenance scope and break
   the independent product boundary.
6. **Avoid branding and licensing assumptions.** CROWN public brand assets
   and third-party vendor artwork cannot automatically be taken as Jireh
   standalone trademarks or properly licensed assets. Use new owner-approved
   Jireh branding and a source/licensing register for any image or icon reuse.
7. **Keep Jireh SGO separate.** `backend/jireh_sgo` and SGO frontend files
   address a separate product; their endpoints, award scopes and processing
   should not silently become part of the Jireh financial-aid standalone.
8. **No automatic conversion of CROWN formulas.** The previously archived
   award calculator and the separate CROWN need-index may have conflicting
   assumptions and mission/religious factors. Preserve only as history
   pending owner, fairness, legal/privacy and financial-policy decisions.
9. **No confidential data in public source.** The checked repos are public;
   do not commit buyer contacts, unapproved business terms, real households,
   documents, credentials, private financial statements or confidential
   commercial plans.

## Prioritized independent product work

**P1 — immediately usable historical acceptance evidence:**
- Preserve pure reporting reference and stand-alone Python test harness (this
  PR). Add *new* Jireh-specific tests in later implementation for exact
  household/year identity, missing-versus-zero, unknown/unauthorized report
  state, revocation, and non-cash award face value.
- Keep the UI no-fallback contract, no misleading status and
  canonical-readback requirements as acceptance criteria for the eventual
  web experience; do not activate a dashboard before verified data sources.

**P2 — after product field and operational privacy approval:**
- Adopt school-specific family questionnaire UX, accessible error/empty/loading
  states and server-persisted confirmation with independent Jireh API client.
- Implement school officer review with write outcome reconciliation,
  duplicate-offer prevention and safe audit, **only after** issue #47 policy
  approval; restore source tests as references without CROWN ORM dependencies.

**P3 — after reporting and hosting authorization:**
- A single source-bound, authorized aggregate reporting endpoint that exposes
  only approved metrics; reporting exports with minimal fields, safe CSV
  escaping, audit, explicit school roles and rate limits; UI only then.
- Human-approved Jireh logo, typography, color tokens and accessibility design,
  with UI snapshots and Playwright acceptance tests. Rebuild rather than
  coupling to CROWN dashboards.

## Implementation and verification limits

Source reference in `tests/legacy_crown/financial_aid_reporting.py` preserves
the text of `FinancialAidDashboardIntegrityError`, `_same_id`, `_money`
and `summarize_financial_aid_rows` up to the ORM producer. Check that the
function implementation matches the original source after newline
normalization. Existing historical CROWN data-model keys are **not** the
standalone Jireh reporting schema. The separately authored
`tests/test_crown_reporting_parity.py` tests only this reference module.
No migrations, application route, reporting service, React view, dependency,
credentials, Azure settings or payment integration changed.

**Do not close #43, #44, #45, #46 or #47 on the basis of this assessment.**
Historical parity does not certify a school reporting system, clinical/legal
compliance, payment balances, hosted demo or production.
