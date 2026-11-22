# Standalone Jireh — reused CROWN wizard primitives

This folder is a **component-only** first migration increment; it does not expose a customer-facing UI, handle financial data, enable submissions, or make any server/API/award writes.

Source: `Arete0920/Crown-CSMS@46b56609fe18360299b08eabaa8bccdffb356a0e`, with these files copied without content changes:

- `frontend/dashboards/src/components/crown/CrownWizard.jsx`
- `frontend/dashboards/src/components/crown/CrownWizard.test.jsx`
- `frontend/dashboards/src/components/crown/CrownWizardStepHeader.jsx`
- `frontend/dashboards/src/styles/crown-theme.css`
- `frontend/dashboards/src/styles/crown-wizard.css`

The `goPrev`/`goBack` behavior from CROWN PR #739 and the original regression tests are retained. Existing style tokens are reused rather than redrawn. This library deliberately excludes CROWN auth, organization roles, applications, payments/ledger, and presentation routes.

The package versions and transitive lock entries are a selected dependency closure from the same CROWN package-lock.json, not a broad copy of the full CROWN app.

```sh
cd frontend
npm ci
npm run test
npm run build
```

**Next separately reviewed stages:** adapt the six existing officer wizard steps and Jireh-specific authorized APIs; adapt the family workflow and original dashboards/widgets. Maintain separation from CROWN runtime, with reviewed methodology, consent, and award controls before any write-enabled UI. No production readiness is inferred from these component tests.
