# Jireh — localhost synthetic browser demonstration

**Status:** Test-only, not a deployed or production-ready application.
**Intended demo:** December 1, 2026 (guided preview of implemented capabilities).

This prototype renders an actual local browser interface backed by the same
Django household, annual draft, selected-student and school-director endpoints
used by the regression tests. All sample users, students, and schools are
fictional and recreated in a disposable local SQLite database.

## Start it on a developer workstation

The standalone repository's Python 3.12 runtime requirements must first be
installed from the pinned, hashed `requirements.txt` as in the README.

```sh
python scripts/run_local_browser_demo.py
```

Open **http://127.0.0.1:8765/local-demo/** on the *same workstation*.

The runner deliberately refuses a non-demo Django settings module, pre-set
database path or enabled Jireh runtime flag. It creates a private temporary
directory, applies migrations only to the temporary SQLite database, seeds
fictional records, and binds the test server only to `127.0.0.1:8765`.
Ctrl+C stops the server and deletes its temporary database. No Azure/cloud
service or production URL routing is used.

**Do not expose, port-forward, tunnel, reverse-proxy or deploy this local
server.** The synthetic usernames and per-process randomly generated
credentials are not customer authentication; localhost sessions use test-only cookies
over loopback HTTP. Do not use on untrusted workstations or with real data.

## Browser walkthrough

1. **Family applicant:** Sign in using the synthetic family persona. The UI
   reads the authorized household and linked children.
2. **Create/resume draft:** Create an annual DRAFT for one school and year.
   Repeating the action returns the same draft.
3. **Select two children:** Each child is selected idempotently and linked
   to that family draft.
4. **Cross-school and CSRF checks:** The UI deliberately exercises rejected
   School B access and rejects a request missing its CSRF header.
5. **School A director:** Switch personas (logging out the prior account)
   and see the school's read-only draft inventory.
6. **School B director:** See that this director cannot read School A's
   inventory and has no School B drafts.

## Optional Playwright screenshots and video

For actual browser evidence, install Playwright and Chromium in an isolated
development environment (these are NOT application dependencies):

```sh
python -m pip install playwright
python -m playwright install chromium
python scripts/verify_local_browser_demo.py
```

The script starts the same loopback-only disposable demo, drives a Chromium
session and asserts the visible family and director workflows. On success,
it writes synthetic-only screenshots and video under
`artifacts/synthetic-demo/`. **That run is not yet certified until its
logs, screenshots and video are captured and independently inspected.**
Never commit real family data, credential files, or sensitive screenshots.

The ordinary Django/SQLite and PostgreSQL CI suites verify the browser
interface's HTTP routes, user-session separation, two-school boundary, CSRF
and idempotency. Those automated HTTP tests are not substitutes for actual
Playwright browser evidence.

## Limitations (present during every demonstration)

- **Working:** Test-only family sign-in, household/child listing, annual draft
  creation and resume, child selection, authorized director inventory,
  cross-school denial, and CSRF checks.
- **Not implemented here:** Financial questionnaire, tax document upload,
  consent/final submission, automated assessment, school award decisions,
  fees/payment, real onboarding, SIS integrations or a production service.
- **Not represented:** Production security sign-off, real-world identity
  verification, monitoring, incident response, document protection, and
  recoverability.

This browser implementation extends the backend rehearsal in PR #52 and is
part of [issue #42](https://github.com/Arete0920/Jirehfinancialaid/issues/42).
Issue #42 must stay open until the required actual browser acceptance evidence
and owner-approved presentation claims are available.
