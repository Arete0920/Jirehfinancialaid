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

## December 1 guided technical-preview packet — owner approval pending

**Approval status: NOT APPROVED FOR PRESENTATION.** The product owner must approve the exact
presenter language and audience before any buyer-facing use. The following script
describes only the already implemented, synthetic local browser journey; it
does **not** authorize deployment, real-family intake, payment, or school onboarding.

### Exact-commit engineering evidence (2026-11-22)

- Verified protected `main` baseline: `730a1a5ac46b84be4b6795c55c664547a1fa51a4`.
- [Foundation checks — run 45049851530](https://github.com/Arete0920/Jirehfinancialaid/actions/runs/45049851530):
  Python contracts, Django tests, PostgreSQL 16 integrity, and SonarCloud PASS.
- [Chromium browser E2E — run 45049851532](https://github.com/Arete0920/Jirehfinancialaid/actions/runs/45049851532):
  PASS on that exact merged SHA, including draft resume, selected children,
  active journey steps, director inventories, CSRF denial and two-school denial.
- [Screenshot/video artifact 14765275764](https://github.com/Arete0920/Jirehfinancialaid/actions/runs/45049851532/artifacts/14765275764):
  downloaded and SHA-256 verified against GitHub digest
  `1f033c3aa069a29b70e43f585c7c7fa12a8dfd932feec85ee63a5a36e3a32d39`.
  All three PNG screenshots were visually inspected. A WebM recording exists,
  but its playback has **not** been independently reviewed.
  GitHub retention expires on **2026-12-06**.
- These are **engineering tests, not production certification**. If the checkout
  SHA changes, repeat and record the appropriate checks for the new SHA;
  never reuse this evidence to certify a different build.

### Proposed opening and walkthrough (not owner-approved)

> "This is a local, synthetic technical preview of standalone Jireh Financial
> Aid. The schools, people and records are fictional. You will see the working
> annual application **draft** and school-access boundaries, not a complete
> financial-aid application or a production service."

| Sequence | Presenter action | Permitted observation |
| --- | --- | --- |
| 1 | Start the demo on a trusted workstation; open `http://127.0.0.1:8765/local-demo/` | Explicit LOCAL SYNTHETIC DEMO / NOT LIVE disclosure |
| 2 | Select **Family applicant** | Synthetic sign-in, authorized School A household and its two linked children |
| 3 | Select **Create / resume annual draft**, then choose both children | One school/year DRAFT and two idempotent linked-child selections |
| 4 | Select **Family applicant** again | The existing DRAFT and both selected children reappear after sign-in |
| 5 | Run **Verify School B access is denied** and **Verify CSRF protection** | Test-only 404 cross-school denial and 403 missing-CSRF rejection |
| 6 | Switch to **School A director**, then **School B director** | Read-only School A draft count of one; School B count of zero; cross-school staff denial |

The presenter may show the local display over a screen-sharing session
containing **fictional data only**, without exposing the local server to
other machines. Do not port-forward, reverse-proxy, tunnel, or publish the
demo URL. Do not imply that a viewer can sign into a hosted product.

### Required closing disclosure

> "Financial questions and documents, final consent and submission,
> financial need calculations, award decisions, payments, real-school
> onboarding, and hosted customer access are **not implemented in this
> demonstration**. These security and operational workflows have not received
> production acceptance. No real family information may be entered."

**No unverified claims:** Do not describe the financial aid form as completed,
the award engine as operating, the synthetic login as production identity
verification, the 404 checks as proof of all deployed tenant isolation, the
`/healthz/` endpoint as production readiness, or any payment capability as
active. Do not label the product compliant or commercially ready without
separate evidence and approvals.

### Sign-off and stop conditions

- [x] Exact-main automated browser and foundation checks captured; screenshots
  inspected as described above.
- [ ] Product owner approves the **opening, walkthrough, closing disclosure,
  audience and technical-preview designation** in
  [issue #42](https://github.com/Arete0920/Jirehfinancialaid/issues/42).
- [ ] Presenter completes a dry-run using the exact checked-out commit,
  confirms every demonstrated status, and records date, SHA and result.
- [ ] Confirm the session uses synthetic personas only and a trusted,
  loopback-only workstation (or screen share of that workstation).
- [ ] Record the approved demo date, presenter, and any observed deviation
  with evidence in issue #42.

If any test fails, a real person/school record appears, a forbidden route
becomes accessible, or evidence no longer matches the checkout, **stop
presentation and retain NO-GO** until the issue is resolved. This acceptance
packet is intentionally distinct from the eleven production release gates in
`docs/PRODUCTION_READINESS.md`; completing the demo never enables production.

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
