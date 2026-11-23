# Standalone Jireh — synthetic guided demonstration rehearsal

Rehearse fictional household onboarding, annual drafts, and school-director
inventory. A second fictional school exercises access isolation.

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
invokes Django's test runner for three synthetic scenarios across two modules.
The test runner creates and destroys its test database. It does **not**
start a server, expose a customer endpoint or apply live migrations.

The GitHub foundation workflow runs both modules with disposable PostgreSQL 16
and the established integrity checks on pull requests targeting `main`.
Review the actual log, workflow run and exact candidate commit; do not
claim acceptance merely because this document exists.

## Guided presenter walkthrough

The draft walkthrough prints and asserts these `DEMO` steps.

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

The runner also tests onboarding. A fictional family signs in without a grant,
redeems two codes from Django's in-memory mailbox, and gains household access.
Revocation blocks that access in the same session. The test also exercises
cross-school denial and single-use redemption.

To start before the director has a grant, use the separate [first-director
rehearsal command](../README.md#development-checks). Two operators sign the
proposal and approval with synthetic WebAuthn credentials. Invitation attempts
are denied until approval records the grant. The test then runs the household
onboarding sequence.

## Acceptance and evidence to retain

- Exact branch and head SHA, GitHub PR URL, check conclusions, and Django and
  PostgreSQL logs for the exercised scenarios.
- Preserve the sample script output or captured console recording,
  if desired. It contains synthetic identifiers and no real financial data.
- For browser evidence, run `python scripts/verify_local_browser_demo.py`
  separately. It captures screenshots and video from the localhost walkthrough.
- A demo presenter must state the prototype's limits before showing the
  flow; do not claim the first-school product is production ready.

## Scope of issue #42 acceptance

[Issue #42](https://github.com/Arete0920/Jirehfinancialaid/issues/42) closed for
the approved synthetic demonstration. First-school operational acceptance,
including hosted delivery and institutional identity verification, remains
in [issue #49](https://github.com/Arete0920/Jirehfinancialaid/issues/49).
