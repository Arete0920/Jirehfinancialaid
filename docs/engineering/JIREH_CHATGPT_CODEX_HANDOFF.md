# Jireh ChatGPT/Codex Handoff

**Repository:** `Arete0920/Jirehfinancialaid`  
**Prepared:** 2026-11-21  
**Purpose:** Transfer current repository state and engineering constraints to ChatGPT/Codex without implying that Jireh is already a standalone or commercially ready product.

## Handoff summary

Jireh is to become an independent school financial-aid solution that can optionally integrate with CROWN CSMS and SIS or school-management vendors. Jireh SGO is excluded from the current solution scope.

The repository is a broad source copy of CROWN CSMS, not a completed Jireh extraction. It contains shared CROWN identity, authorization, tenant, student, family, aid, financial, dashboard, and wizard dependencies. It does not yet prove that Jireh can run, recover, secure, support, and sell independently.

Do not infer missing requirements from existing code. Do not preserve SGO as a product requirement unless the owner later explicitly restores it.

## Current exact state

- Jireh repository branch: `copilot/new-repository-for-jireh`
- Jireh handoff base: commit `7af19263dad476226e4855ee1148baa3200ceba3`
- CROWN source baseline: `ac9fab0981c281f9815b20160d37da4fa8e5bd1f`
- Repository overview: `README.md`
- Azure credentials, resources, domains, DNS, deployment workflows, and live hosting are not configured in this repository.
- GitHub workflows, agent instructions, Crown-specific editor tasks, operational audit evidence, and a private key were excluded during migration.
- `.venv`, `.local-backups`, frontend dependencies, and frontend build output are local or ignored state, not source evidence.

## Product scope

### First product boundary

Build and verify a standalone school financial-aid product for:

- school onboarding;
- authorized school staff roles;
- family and applicant access;
- student/household records;
- academic-year setup;
- aid applications;
- document or data intake only if separately approved;
- needs assessment and policy configuration;
- committee review and recommendations;
- award decisions and award letters;
- renewals and status tracking;
- reconciliation and reporting;
- audit history;
- customer support and operational recovery.

### Excluded now

- Jireh SGO organizations, applications, eligibility, custody, awards, funding, or settlement;
- external payments or money movement;
- Azure activation or DNS changes;
- real customer or student data;
- claims of production readiness.

### Optional integration

CROWN and external SIS vendors such as Gradelink or Rediker may be integration targets later, but integration is optional and must not be required for Jireh to operate.

No vendor integration is currently certified. Gradelink and Rediker integration pages show generally available integration patterns, but no agreement, API authorization, data model, partnership, or certification with Jireh has been established.

For integrations, establish:

- explicit system-of-record ownership;
- canonical school, family, student, applicant, and award identifiers;
- read/write boundaries;
- sync failure and retry behavior;
- conflict resolution;
- tenant isolation;
- minimum necessary data;
- authentication, authorization, secrets, and key rotation;
- FERPA and contract review;
- deletion and retention behavior;
- end-to-end and replay tests.

## Verified current evidence

Observed locally on 2026-11-21:

- Jireh static-site tests: 5 passed.
- Dashboard build: passed.
- Eight focused aid/SGO frontend test files: 85 passed.
- Django system check: passed.
- Django migration consistency check: no changes detected.
- Focused fictional aid, authorization, award, and SGO API suite: 31 tests and 17 subtests passed.
- Chromium fictional parent aid submission/readback: 2 passed.

These checks are source and local-synthetic evidence only. They do not certify:

- standalone deployment;
- independent recovery;
- real-browser school staff review and approval;
- award renewals;
- billing or financial reconciliation;
- SGO production capability;
- vendor integration;
- hosted Azure operation;
- FERPA/privacy/contract compliance;
- commercial readiness.

## Important source locations

- `README.md`
- `docs/engineering/DEV_SETUP.md`
- `docs/operations/JIREH_FAMILY_WEBSITE_MIGRATION_20261015.md`
- `docs/sandbox/UNIVERSAL_JIREH.md`
- `docs/product/JIREH_SGO_FOUNDATION.md` — historical/current boundary reference; SGO is excluded from the new product scope.
- `docs/jireh-sgo-fictional-intake.md` — fictional SGO-only test boundary, not a Jireh requirement.
- `backend/aid/`
- `backend/financial_aid/`
- `backend/crown_api/dashboards/`
- `frontend/dashboards/src/pages/FinancialAidWizard.jsx`
- `frontend/dashboards/src/pages/FinancialAidDashboard.jsx`
- `frontend/dashboards/src/pages/ParentFinancialAidPreparationPage.jsx`
- `frontend/dashboards/src/pages/JirehAidDecisionsPage.jsx`
- `frontend/dashboards/src/config/dashboardTemplates/financialAidDashboard.js`
- `frontend/dashboards/tests/e2e/sandbox-parent-financial-aid-submit.spec.ts`
- `backend/sandbox_demo/test_universal_jireh.py`
- `sites/jireh/`
- `sites/shared/product-theme.css`
- `NOTICE.md`
- `docs/brand/BRAND_ASSET_INTAKE_CHECKLIST.md`

## Known implementation cautions

The copied baseline includes two parallel financial-aid implementations:

- `backend/aid/` has direct dependencies on CROWN schools, families, users, finance, ledger, and households.
- `backend/financial_aid/` also represents aid concepts with separate models and routes.

Do not treat these implementations as interchangeable or merge or remove them without an exact data, API, migration, authorization, audit, and rollback plan.

The financial-aid dashboard template contains illustrative snapshot metrics. The active dashboard code currently withholds those metrics and requires separate live-data verification.

The Jireh website is a non-indexed staging candidate and not deployed. The marketing registration flow is not implemented or certified.

## Required handoff inputs not yet verified

The next agent must ask the owner to provide or identify authoritative copies of:

- the complete school-aid product requirements;
- approved customer journeys and acceptance criteria;
- school onboarding and role requirements;
- award, appeal, renewal, communication, and reconciliation rules;
- privacy, retention, consent, accessibility, support, and legal requirements;
- Google Drive and OneDrive indexes or exports;
- external asset provenance and Jireh branding approval;
- contractual rights and intellectual-property evidence;
- target-vendor integration requirements;
- partner, pricing, licensing, and commercial terms.

Do not describe external documents as reviewed until their exact files and review dates are recorded.

## Recommended next increment

1. Remove SGO and CROWN-release assumptions from Jireh-specific planning documents.
2. Inventory Jireh-only requirements and implementation against a school-aid-only acceptance matrix.
3. Identify and isolate CROWN-specific dependencies.
4. Define Jireh's own identity, school, family, student, application, award, ledger/audit, and reporting boundaries.
5. Implement one complete fictional end-to-end school-aid journey: setup, application, review, offer, acceptance, reporting, renewal, and replay.
6. Establish standalone CI, migration, backup/restore, security, privacy, and accessibility gates.
7. Add optional CROWN and vendor integration contracts only after standalone acceptance.
8. Add hosted infrastructure only after explicit owner approval; Azure remains deferred.

## Instructions for the next agent

- Preserve Crown CSMS and all existing work. Do not delete source as a shortcut.
- Work from the current Jireh repository and exact commit.
- Treat this handoff, the repository README, and owner instructions as context, not evidence of production acceptance.
- Keep SGO out of the current implementation scope.
- Use fictional or synthetic data only.
- Do not enable Azure, DNS, payments, live financial authority, or external student-data feeds.
- Do not copy secrets or generated local state into commits.
- Make the smallest coherent change and record exact base/head SHAs.
- Run existing focused tests before broad tests.
- Report unverified claims explicitly instead of converting them into product claims.
- Preserve a reversible rollback path and one coherent pull request per outcome.

## Prompt to paste into ChatGPT/Codex

> We are continuing the Jireh school-financial-aid standalone project in `Arete0920/Jirehfinancialaid`. Read `docs/engineering/JIREH_CHATGPT_CODEX_HANDOFF.md` and `README.md` first. Jireh SGO is excluded from the current scope. Preserve the CROWN repository and existing Jireh source. Do not enable Azure, live payments, DNS, or real customer data. Identify the standalone school-aid requirements and dependencies before changing code. Use the pinned repository state and explicitly label anything not verified. Do not delete or replace existing work to make progress; use small reversible changes.
