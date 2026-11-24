# Jireh — localhost synthetic browser demonstration

**Status:** Test-only, not a deployed or production-ready application.
**Presentation:** Owner approved the original synthetic walkthrough on November 22, 2026. The expanded family, school-director and Arete-operator presentation requires exact-commit browser evidence and separate owner approval of the expanded claims and audience. Use the manual presenter guide in the local browser; there is no autoplay.

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

## Guided sales presentation — live presenter, manual pacing

Allow about 12–15 minutes plus questions. On a trusted workstation, start the
loopback demo and expand **Presenter guide — manual, no autoplay**. Do not
record a click-through as a substitute for a presenter verifying the actual
saved results. The walkthrough is an engineering demonstration, not a live
customer offering or a production acceptance decision.

Opening: "Jireh is designed as an independent financial-aid solution.
Today I will demonstrate a fictional family's annual draft, the school's
review and the Arete operations view. All people, schools, amounts and
records shown here are fictional; no real application or payment is processed."

| Chapter | Presenter action | Required observation before continuing |
| --- | --- | --- |
| 1. Family draft (2 min) | Select **Family applicant**, create/resume the annual draft, select both children; sign in again. | Synthetic Christian Academy; one saved DRAFT; both selections persist. |
| 2. Fictional intake (2 min) | Select a fixed example scenario and **Validate fictional questionnaire**. On supported Linux/WSL2 with the pinned crypto dependencies, add, read and delete the fixed fictional PDF. | Example validation only, no answers saved; encrypted sample independently read and deleted. No real upload control or production scanning claim. |
| 3. Receipt and tenant boundary (2 min) | Verify School B access and CSRF denial, then attest and select **Record fictional receipt**. | Cross-school 404, missing-CSRF 403, independently verified receipt; application remains DRAFT. |
| 4. Director review (3 min) | Select **School A director**, open **View selected children**, preview both fixed assessment scenarios, and record the fictional $250 need offer once. | Two child links; $92.00 Modest and $159.67 Moderate test-policy previews; $250 independently verified fictional offer, not a recommendation derived from either preview. |
| 5. Director workload (1–2 min) | Open **View verified school workload**. Explain each saved metric and return to the walkthrough. | For this fresh one-household scenario: 1 draft, 1 distinct household, 2 child links, 1 fictional receipt, 1 fictional offer, $250.00 fictional face value. No real submitted, accepted, payable or disbursed aid. |
| 6. Family readback and isolation (2 min) | Select **Family applicant**, read fictional offered aid; select **School B director**, verify other-school denial and open its workload. | Family sees its own $250.00 need example; School B's six workload metrics are zero, with its own school heading. |
| 7. Arete command center (1–2 min) | Return, select **Arete platform operator**, and open **View fictional school readiness**. | Exactly two saved fictional schools, their academic years and director-grant counts, setup marked Fictional seed only and SIS marked Not configured. No provisioning or activation control. |

Pause after each chapter. If a required observation fails or independent
readback is uncertain, stop rather than repeatedly submitting a write.
Do not skip the family readback or School B check. If the optional encrypted
document prerequisites are absent, disclose the limitation and omit that
chapter's document action; do not claim that document behavior was demonstrated.

### CROWN behavioral reuse (no CROWN runtime dependencies)

- The [CROWN school/year dashboard read model](https://github.com/Arete0920/Crown-CSMS/blob/46b56609fe18360299b08eabaa8bccdffb356a0e/backend/crown_api/dashboards/financial_aid_live.py)
  supplies the design principle of counting records rather than students or
  cash, enforcing school/year scope and rejecting inconsistent records. The
  standalone Jireh director report uses Jireh's grants and saved fictional records
  ([merged PR #105](https://github.com/Arete0920/Jirehfinancialaid/pull/105)).
- The [CROWN platform-operations registry](https://github.com/Arete0920/Crown-CSMS/blob/46b56609fe18360299b08eabaa8bccdffb356a0e/frontend/dashboards/src/views/platformOps/PlatformOpsHome.jsx)
  supplies the registry and status-view pattern only. Jireh's isolated fictional
  overview ([merged PR #108](https://github.com/Arete0920/Jirehfinancialaid/pull/108))
  uses independent Jireh school, academic-year and grant records. It does not
  reuse CROWN tenant profiles, HTTP services, payment fields or creation controls.
- The outstanding job architecture and two-person provisioning authority stay
  in [issue #109](https://github.com/Arete0920/Jirehfinancialaid/issues/109).
  No claim of operational school provisioning follows from viewing the registry.

### Expanded engineering checkpoint

The source baseline for this expanded script is [main at PR #108's merge](https://github.com/Arete0920/Jirehfinancialaid/commit/761d5d65b9c39b5a416c6b100de9a3a71b8dc7c6).
Its [PR-head foundation](https://github.com/Arete0920/Jirehfinancialaid/actions/runs/45319138524),
[browser](https://github.com/Arete0920/Jirehfinancialaid/actions/runs/45319138509)
and [repository presentation](https://github.com/Arete0920/Jirehfinancialaid/actions/runs/45319138474)
workflows concluded success. They are not post-merge or expanded-script evidence.
The expanded browser test must independently capture the manual guide, the
director dashboard before and after the offer, School B's empty dashboard and
the operator registry. Retain the exact-SHA run, screenshots and video; no
expanded presentation is accepted until those results and the claims are reviewed.

## Fictional document safety boundary

The document example reuses the standalone synthetic lifecycle
(`create_synthetic_document`, `read_synthetic_document`,
`delete_synthetic_document`) and the existing local AES-GCM backend.
Storage is a private temporary directory with a per-process ephemeral key.
The only possible content is a fixed PDF generated by the server, verified by a
fixture-only scanner. This scanner cannot assess real files for malware.
The local AES-GCM backend requires a POSIX filesystem and OS protections
(`O_NOFOLLOW`, owner-controlled mode `0700`). On a Windows developer laptop,
run this particular document demo inside Linux/WSL2; native Windows Python
cannot create the encrypted sample and should fail closed. No weaker Windows
storage fallback is enabled. To exercise the encrypted fictional document
on Linux/WSL2, install both existing hash-pinned dependency sets before running
the demo:

```sh
python -m pip install --only-binary=:all: --require-hashes -r requirements.txt -r requirements-webauthn-ci.txt
```

If these optional preproduction crypto dependencies are not installed, the
other fictional demo workflows remain available; the document create action
returns an unavailable response without writing a document.
No files are uploaded or production customer routes activated. The generic
acceptance workspace includes four editable fictional financial sections with
encrypted, revision-bound persistence when its existing crypto dependencies
are installed. Do not enter real records. The key and temporary database are
disposable; a fresh process creates a new demo. This is not the complete
31-field questionnaire, approved consent, production key management, or live
collection. The temporary files disappear when the local process exits.

Django HTTP tests cover exact family-grant authorization, School B denial,
revoke-with-existing-file, malformed input, CSRF, idempotent create/delete,
metadata-only listing, authenticated PDF readback and absence from production
URL routing. Playwright verifies visible create/read/delete controls in the
synthetic family walkthrough. This is valuable development evidence, **not**
approval for real financial-document intake or operational data security.

## Optional Playwright screenshots and video

For actual browser evidence, install Playwright and Chromium in an isolated
development environment (these are NOT application dependencies):

```sh
python -m pip install playwright
python -m playwright install chromium
python scripts/verify_local_browser_demo.py
```

The script starts the same loopback-only disposable demo, drives a Chromium
session and asserts the visible family, director, school-isolation, manual
presenter guide and operator workflows. On success,
it writes synthetic-only screenshots and video under
`artifacts/synthetic-demo/`. **That run is not yet certified until its
logs, screenshots and video are captured and independently inspected.**
Never commit real family data, credential files, or sensitive screenshots.

The ordinary Django/SQLite and PostgreSQL CI suites verify the browser
interface's HTTP routes, user-session separation, two-school boundary, CSRF
and idempotency. Those automated HTTP tests are not substitutes for actual
Playwright browser evidence.

## Owner-approved initial walkthrough — expanded scenario pending acceptance

**Approval status:** The owner approved the initial fictional family/draft/director walkthrough and its laptop presentation on November 22, 2026 (Issue #42). **Approval of the expanded fictional $250 sequence and any particular buyer-facing audience must be separately recorded after exact-commit evidence is reviewed.** The following script
describes only the already implemented, synthetic local browser journey; it
does **not** authorize deployment, real-family intake, payment, or school onboarding.

### Historical baseline engineering evidence (not the expanded $250 scenario)

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

### Original baseline opening and walkthrough (expanded steps separately reviewed)

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

> "We demonstrated fixed fictional questionnaire examples, a fixed encrypted
> sample document when supported, a fictional receipt and offer, school-scoped
> director reporting, and a read-only Arete registry. Real financial-answer
> collection, customer document uploads, legal consent and final submission,
> binding award decisions, payment, real-school provisioning, live SIS
> connections, and hosted customer access are not enabled. The fictional
> $250 offer is not a funding promise. No real family data may be entered."

**No unverified claims:** Do not describe the financial aid form as completed,
the award engine as operating, the synthetic login as production identity
verification, the 404 checks as proof of all deployed tenant isolation, the
`/healthz/` endpoint as production readiness, or any payment capability as
active. Do not label the product compliant or commercially ready without
separate evidence and approvals.

### Sign-off and stop conditions

- [x] Historical original-workflow exact-main browser and foundation evidence
  captured and screenshots inspected as described above.
- [ ] Expanded exact-commit browser and foundation checks pass; review the
  guide, director before/after/empty reports, operator screenshots and video.
- [ ] Product owner approves the expanded **opening, walkthrough, closing
  disclosure, audience and technical-preview designation** in
  [issue #47](https://github.com/Arete0920/Jirehfinancialaid/issues/47) and
  [issue #109](https://github.com/Arete0920/Jirehfinancialaid/issues/109).
- [ ] Presenter completes a dry-run using the exact checked-out commit,
  confirms every demonstrated status, and records date, SHA and result.
- [ ] Confirm the session uses synthetic personas only and a trusted,
  loopback-only workstation (or screen share of that workstation).
- [ ] Record the approved demo date, presenter, and any observed deviation
  with evidence in the applicable open issue (#47 or #109); retain #42 as
  the historical baseline approval.

If any test fails, a real person/school record appears, a forbidden route
becomes accessible, or evidence no longer matches the checkout, **stop
presentation and retain NO-GO** until the issue is resolved. This acceptance
packet is intentionally distinct from the eleven production release gates in
`docs/PRODUCTION_READINESS.md`; completing the demo never enables production.

## Limitations (present during every demonstration)

- **Working:** Test-only family sign-in, household/child listing, annual draft
  creation and resume, child selection, authorized director inventory,
  cross-school denial, and CSRF checks.
- **Fictional assessment preview:** As the School A director, open the selected
  draft and choose a scenario. The versioned test policy shows **$92.00** for
  Modest, including a **$50.00** capped hardship line, and **$159.67** for Moderate.
  These read-only results use fixed fictional inputs. The separate $250 offer in
  the walkthrough uses its own fixed example amount.
- **Synthetic-only source features:** Fixed questionnaire validation without
  saving answers, fixed encrypted sample lifecycle, immutable fictional receipt,
  director-authorized fixed $250 example, family-scoped readback, school/year
  workload report and read-only Arete school registry. These are not real
  submissions, awards, ledger postings or operational provisioning.
- **Not enabled:** Real questionnaire intake, tax document uploads, legal
  consent/final submission, live family assessment, binding awards, fees/payment,
  actual school activation, live SIS integrations or production customer routes.
- **Not represented:** Production security sign-off, real-world identity
  verification, monitoring, incident response, document protection, and
  recoverability.

This browser implementation extends the backend rehearsal in PR #52 and is
part of [issue #42](https://github.com/Arete0920/Jirehfinancialaid/issues/42).
Issue #42 was closed for the previously approved synthetic walkthrough.
The expanded family → officer → family flow remains tracked under #47 until
its new browser evidence and presentation claims are separately accepted.
