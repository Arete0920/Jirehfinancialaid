# Standalone Jireh production readiness — NO-GO

**Status:** NO-GO. **Scope:** `Arete0920/Jirehfinancialaid`, not CROWN.
**Current verified protected-main source checkpoint (2026-11-23 Eastern / 2026-11-24 UTC):**
[`01dd98e41fce16075f4d4ae74425b64689f3cc75`](https://github.com/Arete0920/Jirehfinancialaid/commit/01dd98e41fce16075f4d4ae74425b64689f3cc75), merged
[PR #105](https://github.com/Arete0920/Jirehfinancialaid/pull/105) — **six completed SUCCESS checks**:
Python 3.12 contracts, Django 5.2, disposable PostgreSQL 16 integrity,
synthetic localhost Chromium E2E, SonarCloud, and repository presentation.
Exact-commit runs: [foundation 45313276198](https://github.com/Arete0920/Jirehfinancialaid/actions/runs/45313276198),
[browser 45313276177](https://github.com/Arete0920/Jirehfinancialaid/actions/runs/45313276177),
[presentation 45313276210](https://github.com/Arete0920/Jirehfinancialaid/actions/runs/45313276210).
[PRs #100](https://github.com/Arete0920/Jirehfinancialaid/pull/100),
[#102](https://github.com/Arete0920/Jirehfinancialaid/pull/102),
[#103](https://github.com/Arete0920/Jirehfinancialaid/pull/103),
[#104](https://github.com/Arete0920/Jirehfinancialaid/pull/104), and
[#105](https://github.com/Arete0920/Jirehfinancialaid/pull/105) are **merged**;
do not reassign or rebuild their completed source changes.
**Delivery decision:** the December 1 first-client target is **NO-GO for live paid use** at this checkpoint;
a synthetic prepayment release candidate requires separate acceptance.
**Release status remains NO-GO.**
Keep `JIREH_OPERATOR_CREDENTIAL_RECOVERY_ENABLED` false,
the other privileged WebAuthn gates disabled, and customer routes unexposed.
This document does not authorize creating cloud resources, enabling runtime,
processing payments, collecting real family data, or initiating real recovery.

## Single source of truth and cross-chat coordination

**Authoritative record:** this file is the single Jireh product/release readiness ledger;
protected `main`, current GitHub [issues](https://github.com/Arete0920/Jirehfinancialaid/issues),
[PRs](https://github.com/Arete0920/Jirehfinancialaid/pulls), and exact-SHA
[CI](https://github.com/Arete0920/Jirehfinancialaid/actions) provide the underlying
engineering evidence, issue ownership, and approved decisions. This is **one
GitHub system**, not competing status plans maintained in separate sessions.
Other coordination spaces are navigation/archive aids only.

**Before any change:** refetch protected `main`, open issues/PRs, current head SHAs,
changed-file overlap, branch protections, and all required check conclusions.
Only the explicitly scoped implementer changes an active PR; parallel chats
may provide read-only analysis but cannot assume exclusive ownership.
Record an accepted decision or scope change in the relevant GitHub issue/PR
and reconcile this readiness ledger. Historical SHAs here are dated checkpoints,
not an alternative latest status. No chat can remotely pause other sessions:
stop duplicate writes through explicit coordination and current GitHub checks.

## Evidence classification

- **Source/CI evidence (verified):** the latest protected-main revision listed
  above has six successful check contexts, including the exact-SHA localhost
  browser and disposable PostgreSQL suites. This is evidence for repository
  source and synthetic acceptance only; no deployed customer journey, target
  TLS/DB trust chain, monitored service or live tenant isolation was tested.
- **Synthetic tenant acceptance (verified as test coverage, not production):**
  `src/jireh/financial_aid/test_tenant_http_acceptance.py` is included in
  the Django/PostgreSQL source test suite. It exercises synthetic authenticated
  sessions, two-school denials, separated households sharing a child, revoked
  grants, CSRF and nonmutation. A green aggregate suite establishes that
  its included tests did not fail; it is not evidence of deployed tenant
  isolation or approved live authentication.
- **Standalone runtime exposure (source only):** `src/jireh/runtime/urls.py`
  defines only `GET/HEAD /healthz/` (process liveness) and `GET/HEAD /readyz/`
  (one read-only PostgreSQL `SELECT 1`; generic 503 on database failure).
  Server-generated privacy-minimized correlation IDs/logging are wired in the
  closed runtime. These do not establish schema/migration parity, alert
  delivery or customer routes; test/demo URL routing remains separate.
- **Browser acceptance (source only):** the protected-main synthetic
  Chromium [run 45313276177](https://github.com/Arete0920/Jirehfinancialaid/actions/runs/45313276177)
  concluded SUCCESS on the current verified protected-main SHA. The browser
  exercises fictional localhost workflows only, including the encrypted
  sample-PDF path and readback; it is not a deployable customer browser,
  real upload or operational security PASS.
- **Open PR inventory at this checkpoint (verify live before any writes):**
  [PR #106](https://github.com/Arete0920/Jirehfinancialaid/pull/106)
  is **OPEN DRAFT** for questionnaire privacy/requiredness metadata and
  Q01–Q10 governance safeguards; its exact head
  `192846c05d64bf2c29ad270a1ad6d21f7275ebe8` had six successful
  CI contexts, but green checks do not make an unmerged draft accepted policy.
  [PR #65](https://github.com/Arete0920/Jirehfinancialaid/pull/65)
  is **OPEN** for the CROWN-derived officer wizard. Its latest head had
  successful CI, but two SonarCloud SCA dependency-risk records remain
  unclassified; obtain their authoritative disposition before merge.
  PRs #100, #101, #102, #103, #104 and #105 are **MERGED** and not
  duplicate workstreams.
- **Not established:** live hosting, deployed configuration, authenticated
  production APIs, database read isolation, observability, incident response,
  production backups, restore drills, real operator identity verification,
  WebAuthn hardware backup/counter policy, and security operations acceptance.

Passing source CI or a 200 from `/healthz/` or `/readyz/` is never a
production acceptance decision. The owner expressly defers CompuWerx activity;
$55 household submission must remain nonfinal until authoritative payment
reconciliation. No fake paid status, alternate processor or waived payment may
substitute for this mandatory future acceptance stage.

## Single product-delivery acceptance checklist (no double counting)

**Three separate decisions — not three different products:**

1. **Standalone feature completion:** Implement and test real application
   behavior using only fictional schools/people, with database readback,
   school/household authorization, negative cases, and complete browser flows.
   This can be accomplished without CompuWerx or real family data.
2. **Deployable synthetic release candidate:** Package and verify the *same*
   customer application behind a production-equivalent, security-reviewed
   acceptance environment, with synthetic test records only, live payment
   collection and final paid submission disabled. No production or Azure
   resource change is authorized by this checklist.
3. **Commercial paid application GO:** After owner authorization of the
   CompuWerx stage, separately certify actual provider identity, durable
   server-side $55 household fee reconciliation, state transition, and operational
   controls. A mock-paid browser status is **never** sufficient to mark a
   customer application finally `SUBMITTED`.

**Synthetic test data is the preferred evidence source throughout.** A
successful release does not require any pre-existing real family files or
financial records. The customer environment must still be capable of securing
them when future customers voluntarily submit applications.

| Priority | Complete customer-journey requirement | Current evidence on verified main | Remaining acceptance / dependency |
| --- | --- | --- | --- |
| P0 | Standalone school, household and annual application identity | Unique school/year/household draft, grant checks, multi-child linking, separate-parent negative tests | Accept hosted authentication, exact tenant read/write enforcement, and canonical DB readback |
| P0 | Saved family financial questionnaire | Seven sections and 31 owner-approved *development* field paths, pure validation, fixed fictional preview | School-scoped encrypted answer persistence, save/resume/correction, versioned questions, negative tests; Q01–Q10 detailed retention/consent/financial policy remains incomplete [#43](https://github.com/Arete0920/Jirehfinancialaid/issues/43) |
| P0 | Family-to-officer end-to-end presentation | Local Chromium test performs fictional draft, students, receipt, $250 offer, readback; PR #103 merged | Integrate the **same supported workflow** into independently secured customer runtime; no demo-only credentials or URL configuration |
| P0 | Family consent and final application lifecycle | Synthetic disclosure receipt and offline payment/submission contracts; real `AidApplication` still `DRAFT` | Approved consent version, actor, audit, transactional submission state; preserve mandatory payment reconciliation gate [#45](https://github.com/Arete0920/Jirehfinancialaid/issues/45) |
| P1 | Supporting documents | Authenticated, encrypted, fixed fictional PDF create/read/delete; scanner controls and local negative tests | Approved real file ingestion, malware scanning, key operations, retention/deletion and access policies [#44](https://github.com/Arete0920/Jirehfinancialaid/issues/44) |
| P1 | Need assessment and five aid categories | Fixed fictional scenario calculations with versioned bucket contracts | Approve and validate explainable live methodology; do not treat invented coefficients as eligibility [#46](https://github.com/Arete0920/Jirehfinancialaid/issues/46) |
| P1 | Aid-officer review and offers | School-scoped draft detail, synthetic $250 offer, readback; PR #65 officer wizard unmerged | Review/decision state, two-person audit where applicable, approval workflow, durable results, case reporting and wizard security [#47](https://github.com/Arete0920/Jirehfinancialaid/issues/47) |
| P1 | Director reporting and actual-data truth | PR #105 **merged**: source-backed, director-only school/year workload dashboard with synthetic browser acceptance and no invented fallback metrics | Customer-facing route/identity approval and deployment acceptance still outstanding; do not present synthetic workload as actual submitted aid, awards or disbursements |
| P1 | Household identity, invitations, recovery | Internal grants, invitation and email verification, loopback TLS SMTP rehearsal merged in #101 | Operational identity assurance, real mail delivery, MFA/recovery ceremony and helpdesk acceptance [#49](https://github.com/Arete0920/Jirehfinancialaid/issues/49) |
| P0 | Customer application routing and packaging | Deployed-style Django runtime configuration is fail-closed; production URLConf intentionally includes only `/healthz/` and `/readyz/` | Build/certify secure routes for the actual accepted family/director features; select/approve hosting and target environment |
| P0 | Security, operations and release certification | Six exact-main source checks pass, including disposable PostgreSQL and Chromium; sanitized request telemetry exists | Validate the 11 **target-environment** D/T/S/M/I/A release acceptance gates below, not merely unit/CI status [#48](https://github.com/Arete0920/Jirehfinancialaid/issues/48) |
| Deferred | $55 paid final submission / CompuWerx | Approved one-fee-per-household policy and offline fail-closed reconciliation primitives | No provider-specific activity before owner releases the hold. A synthetically deployable RC is allowed; paid commercial launch is blocked until provider certification [#50](https://github.com/Arete0920/Jirehfinancialaid/issues/50) |

**No synthetic-only feature counts as customer-ready solely because its CI is
green.** Conversely, the eleven target-environment checks below are acceptance
gates, **not eleven failing source tests**. Record product completion, source
checks, target-environment acceptance, and actual business activation separately.

### Execution order

1. Finish independent acceptance of open draft PR #106's questionnaire
   governance tests without duplicating its files. Keep PR #65's wizard
   blocked until the two exact SonarCloud SCA dependency-risk records are
   reviewed and dispositioned. The director dashboard PR #105 is merged.
2. Complete and test the fictional family questionnaire and family/officer
   end-to-end journey; obtain specific Q01–Q10 owner/privacy decisions before
   real financial-answer persistence, migrations, legal consent or customer
   collection routes.
3. Perform secure application integration and synthetic E2E acceptance, with
   realistic two-school identity, financial, document, failure and recovery cases.
4. Approve hosting and validate all target-environment operational gates against
   an immutable release SHA, with synthetic-only records.
5. Present a deployable **prepayment** release candidate for owner acceptance.
   Keep customer final paid submission disabled and continue to block live data
   collection until approved.
6. Begin CompuWerx contract/API/security work **only upon separate owner
   authorization**; certify authoritative reconciliation, then reconsider
   commercial first-client GO.

## Release-blocking acceptance matrix

All checks must have an owner, date, exact immutable SHA, environment,
artifact/log reference, observed outcome, reviewer, and sign-off. Record
**NOT TESTED**, **FAILED**, or **PASS** explicitly; missing evidence is
NOT TESTED and blocks release.

| Gate | Test and required PASS evidence | Current disposition |
| --- | --- | --- |
| D1: deployment architecture | Owner-approved hosting, network and database topology, exposure limits, data residency and cost budget; documented and reviewed | NOT TESTED |
| D2: runtime configuration | Secrets externally managed; `DEBUG=False`; exact allowed hosts; TLS termination/proxy trust, HTTPS redirect, HSTS policy, secure session/CSRF cookies, secure headers, DB cert verification and least-privilege database role confirmed on deployed environment | NOT TESTED |
| D3: release safety | Reproducible artifact provenance, authorized release, integrity verification, migration rehearsal, encrypted backup, restore and rollback drills with measured results and no real data in test reports | NOT TESTED |
| T1: tenant read isolation | Actual authenticated requests for two schools, distinct households, separated parents and distinct staff; cross-school/same-child/superuser/header forgery tests deny without leaking identifiers or financial data; PostgreSQL read-role boundary reviewed | NOT TESTED (synthetic coverage candidate only) |
| T2: tenant mutations | CSRF, idempotency, wrong school/year/household/student denial, before/after data and audit counts, revoked/inactive grants, concurrency, raw SQL integrity, and unauthorized writes tested on PostgreSQL | NOT TESTED end-to-end |
| S1: identity and privilege | Secure live login/onboarding, trusted operator identification, two-person first-director approval, tested MFA challenge/registration/recovery/counter policy, locked-down administrative routes and negative tests | NOT TESTED |
| S2: data protection | Encrypted financial document storage, authorization to each object, retention/deletion policy, data minimization, threat model and secret handling verified | NOT TESTED |
| M1: operational telemetry | Sanitized structured events and correlation IDs; alerts for authentication abuse, privileged grants, credential recovery/revocation, 5xx errors, DB failures and tenant-boundary denials; observed delivery to named responder | NOT TESTED |
| M2: resilience | Readiness distinct from liveness, alert routing and escalation, on-call coverage, backup verification, restore time objectives, recovery drills and safe rollback exercised | NOT TESTED |
| I1: incident exercise | Tabletop and technical drill for lost/compromised key, unauthorized cross-tenant access, credential or secret exposure and database outage; record timestamps, decisions, notifications and immutable evidence | NOT TESTED |
| A1: final approval | All gates PASS for the same release candidate and environment; documented product-owner/integration-manager authorization and security/operations review before activation | NOT TESTED |

## Monitoring and escalation contract (not implemented)

Events must include **timestamp, environment, release SHA, event type,
result, correlation ID, and non-sensitive actor/school pseudonyms** where
necessary. Never log passwords, one-time recovery proofs, WebAuthn assertions,
bearer/session credentials, complete financial records or raw financial
documents. Control access and retention to the approved security policy.

Minimum alert cases and required drill:

1. **Suspected cross-tenant disclosure or unauthorized grant:** notify
   primary security responder immediately, preserve access/audit evidence,
   disable affected access safely, inspect scope, and escalate for breach
   assessment. An HTTP 404 alone is not a substitute for a tracked incident.
2. **Lost or compromised operator authenticator:** suspend sensitive action
   paths, verify operator identity and owner/integration-manager authority
   through an independent trusted channel, preserve reference, and use only a
   separately certified revocation procedure. Never enable the prototype
   credential-recovery flag to improvise an incident response.
3. **Repeated failed login/MFA/recovery or missing audit write:** alert on
   abuse and journal failure, preserve non-secret evidence, keep protected
   operations fail-closed, and investigate attempts without resetting the
   attempt budget to bypass controls.
4. **Availability/database/TLS failures:** stop readiness routing if checks
   fail, alert on-call, establish whether the database connection and
   certificate are trustworthy, and recover only through approved
   documented procedures.

The incident coordinator records severity, discovery time, containment
decision, incident owner, impact assessment, evidence references, escalation
time, communication approvals, corrective actions, and closure sign-off.
Any external legal/privacy notice requires case-specific assessment by the
authorized owner and qualified counsel; this document sets no invented
notification deadlines.

## Operational incident-response procedure (draft; not certified)

1. **Detect and triage:** collect alert and exact deployment SHA, affected
   tenant/actor pseudonyms, timestamps, trace IDs, and sanitized error facts.
   Classify confidentiality, integrity, and availability risk.
2. **Contain:** suspend relevant privileged paths and affected credentials
   using approved controls; preserve tenant data and forensic evidence. Do not
   delete audit rows or disable integrity triggers.
3. **Escalate:** contact the designated incident commander and security
   responder via an independently verified channel. Record each decision.
   Product owner/integration manager controls operational recovery approval.
4. **Investigate:** determine authentication, grant, tenant boundary, database
   writer permissions, origin/TLS or deployment exposure. Maintain an evidence
   chain of custody and do not attach secrets or family financial information
   to GitHub tickets or logs.
5. **Recover:** use reviewed, verified backup/restore or rollback plans;
   independently test recovered tenancy, sessions, revoked keys, migrations,
   audit continuity, and alert delivery before reopening service.
6. **Close:** approve communications and any legal notification, document
   root cause, time to detect/contain/recover, corrective tests, and owner
   acceptance. Restore normal monitoring only after acceptance is recorded.

**Named responders, notification channels, alert thresholds, backup retention,
RPO/RTO, and cloud-provider procedures are intentionally unassigned** pending
approved production architecture. Do not assert these procedures are already
operational.

## Release decision

**NO-GO** until every gate has immutable PASS evidence and designated
human approval. The candidate test suite and this runbook are development
artifacts only. No automatic GO is implied by merging or passing CI.
