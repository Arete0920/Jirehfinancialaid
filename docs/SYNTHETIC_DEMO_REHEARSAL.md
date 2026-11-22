# Standalone Jireh — synthetic guided demonstration rehearsal

**Purpose:** Reproduce the currently implemented one-school household draft
and school-director inventory through authenticated Django test HTTP requests,
with a second synthetic school proving access isolation.

**Status:** Technical rehearsal only. **Not a complete family UI, browser
walkthrough, payment flow, live deployment or production acceptance.** No real
students or school credentials are included.

## Run the verified synthetic flow

Prerequisites: supported Python environment, installed requirements from
`requirements.txt`, and the standalone Jireh source checkout.

```sh
python scripts/rehearse_synthetic_demo.py
```

This runner refuses any non-test `DJANGO_SETTINGS_MODULE`, checks that the
configured database is the in-memory disposable SQLite test database, and
invokes Django's test runner for two reproducible synthetic HTTP scenarios.
The test runner creates and destroys its test database. It does **not**
start a server, expose a customer endpoint or apply live migrations.

For independent PostgreSQL confirmation, use the repository's existing
GitHub pull-request CI. It runs the same test module as part of all Django
tests with disposable PostgreSQL 16 and the established integrity checks.
Review the actual log, workflow run and exact candidate commit; do not
claim acceptance merely because this document exists.

## Guided presenter walkthrough

The rehearsal prints `DEMO` steps in the test output and asserts them:

| Step | Implemented and exercised | Not demonstrated |
| --- | --- | --- |
| 01 | Synthetic parent signs in with session and CSRF protection | Real-family identity proofing |
| 02 | Authorized School A household reads two linked children | Family-facing browser interface |
| 03 | Parent creates and resumes one annual DRAFT | Completed financial questionnaire |
| 04 | Parent selects two children; idempotent repeat requests | Supporting financial documents |
| 05 | Authorized School A aid director reads draft inventory; parent is denied | Financial assessment or award |
| 06 | School B requests and forged school header cannot read or mutate School A data | Production network/database read isolation |
| 07 | Missing CSRF token blocks a state-changing request | Production session operations |
| 08 | Revoking household access blocks an already signed-in parent | Full incident response |
| 09 | School B director cannot see School A applications | Partner and district administration |

No simulated financial need calculation, upload, award, payment or full
application submission is presented as functioning. The prototype exposes
only test routes; the standalone runtime continues to expose liveness only.

## Acceptance and evidence to retain

- Exact branch and head SHA, GitHub PR URL, all four check conclusions,
  logs for both new scenarios on Django and PostgreSQL, and absence of
  production routing changes.
- Preserve the sample script output or captured console recording,
  if desired. It contains synthetic identifiers and no real financial data.
- Show a guided live browser demo **only after** a separately scoped,
  independently tested browser interface exists. Screenshots/video and
  browser E2E evidence are **NOT TESTED** by this rehearsal.
- A demo presenter must state the prototype's limits before showing the
  flow; do not claim the first-school product is production ready.

## Explicit remaining issue #42 gaps

This is the executable **backend rehearsal** portion of issue #42.
The issue cannot be closed until a suitable browser-facing guided flow,
screenshots/video and accepted demonstration claims exist, or the owner
explicitly revises those acceptance criteria. Do not use production data,
provision real schools or alter `jireh.runtime.urls` to satisfy a demo.
