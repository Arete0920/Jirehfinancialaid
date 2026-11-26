# Standalone Jireh production readiness — NO-GO

**Status:** NO-GO. **Scope:** `Arete0920/Jirehfinancialaid`, not CROWN.
**Verified protected-main source checkpoint (2026-11-25 Eastern, 8:48 p.m.):**
[`efc7931db734017d2549301d5005c8ab3e7c483f`](https://github.com/Arete0920/Jirehfinancialaid/commit/efc7931db734017d2549301d5005c8ab3e7c483f), merged [#158](https://github.com/Arete0920/Jirehfinancialaid/pull/158) —
**seven completed SUCCESS check contexts**: Python 3.12 contracts (226/226),
Django 5.2 (676 tests, 62 skipped, no failures), disposable PostgreSQL 16
(676/676, no skips), synthetic Chromium browser acceptance, SonarCloud,
current dependency evidence, and repository presentation.
Exact-commit [foundation 45738204055](https://github.com/Arete0920/Jirehfinancialaid/actions/runs/45738204055),
[browser 45738204108](https://github.com/Arete0920/Jirehfinancialaid/actions/runs/45738204108),
[dependencies 45738204107](https://github.com/Arete0920/Jirehfinancialaid/actions/runs/45738204107), and
[presentation 45738204067](https://github.com/Arete0920/Jirehfinancialaid/actions/runs/45738204067) runs passed.
SonarCloud also passed on this SHA. The Chromium artifact
[15080326064](https://github.com/Arete0920/Jirehfinancialaid/actions/runs/45738204108/artifacts/15080326064)
was present and unexpired at inspection.

**Historical checkpoint:** [#114](https://github.com/Arete0920/Jirehfinancialaid/pull/114) at
[`30d859dd2522e85cc993609a336696e8148cf074`](https://github.com/Arete0920/Jirehfinancialaid/commit/30d859dd2522e85cc993609a336696e8148cf074)
remains historical source evidence; it is not the current implementation baseline.
Current evidence includes [#117](https://github.com/Arete0920/Jirehfinancialaid/pull/117)–[#145](https://github.com/Arete0920/Jirehfinancialaid/pull/145) (workspace, encrypted questionnaire,
documents, review, provisioning, school planning, saved need and decision journal),
[#146](https://github.com/Arete0920/Jirehfinancialaid/pull/146)–[#148](https://github.com/Arete0920/Jirehfinancialaid/pull/148) (changed-income evidence and direct journal privilege audit),
and [#150](https://github.com/Arete0920/Jirehfinancialaid/pull/150), [#152](https://github.com/Arete0920/Jirehfinancialaid/pull/152)–[#158](https://github.com/Arete0920/Jirehfinancialaid/pull/158) (separately guarded customer routes,
authenticated family and director sessions, fixture financial workflow,
director case evidence and independent operator portal).
This is a dated immutable checkpoint. Refetch main and its exact checks before
any subsequent change; do not interpret the ledger as a live inventory.

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
The owner has consolidated implementation into a single execution conversation.
Other coordination spaces are navigation/archive aids only; do not initiate
parallel changes or duplicate earlier implementation.

**Before any change:** refetch protected `main`, open issues/PRs, current head SHAs,
changed-file overlap, branch protections, and all required check conclusions.
Only the explicitly scoped implementer changes an active PR; parallel chats
may provide read-only analysis but cannot assume exclusive ownership.
Record an accepted decision or scope change in the relevant GitHub issue/PR
and reconcile this readiness ledger. Historical SHAs here are dated checkpoints,
not an alternative latest status. No chat can remotely pause other sessions:
stop duplicate writes through explicit coordination and current GitHub checks.

## Evidence classification

- **Source/CI evidence:** seven successful check contexts on the pinned SHA;
  all four recorded push workflows succeeded. The PostgreSQL job verified model
  and migration consistency, selected reversal/reapplication paths and closed
  runtime routing. This is not deployed-environment acceptance.
- **Tenant and identity acceptance:** current suites exercise distinct schools,
  separate households sharing a child, grants, revocation, CSRF and scoped
  mutations. Browser acceptance includes fictional invitation dual-proof
  redemption, family login/draft/selection/readback/logout, director password
  plus virtual WebAuthn signed assertion, and independent operator password
  plus WebAuthn and read-only registry. No live identity provider or real
  institutional onboarding is certified.
- **Runtime exposure:** `src/jireh/runtime/settings.py` still mounts
  `jireh.runtime.urls`, containing only GET/HEAD `/healthz/` and `/readyz/`.
  The latter is a database connectivity check, not schema or release proof.
  Customer core, customer portal, fixture financial portal and operator portal
  URLConfs are separate, guarded acceptance profiles. The authenticated
  financial and operator profiles require disposable identity/database contexts;
  the operator profile expressly excludes customer profile flags.
- **Browser evidence:** the pinned
  [Chromium run](https://github.com/Arete0920/Jirehfinancialaid/actions/runs/45738204108) verified the extracted
  acceptance source, including fictional document selection/version/readback/
  removal, contributor review, changed income, saved need, decision/budget
  readback and the independently authenticated family/director/operator flows.
  These are not proof of a complete single authenticated financial journey
  or production readiness. The manual presenter uses fictional data only.
- **PR inventory at the checkpoint:** 10 open issues and two open PRs,
  [#149](https://github.com/Arete0920/Jirehfinancialaid/pull/149) and [#151](https://github.com/Arete0920/Jirehfinancialaid/pull/151). Both exact branch heads had six passing check
  contexts, but both were behind main. #149 presents current evidence in the
  fictional director workspace; #157 separately adds authenticated director
  case API evidence. Reconcile the functional overlap, do not replace either
  implementation. #151 adds an offline enrollment policy preview and tests;
  no runtime call site or live policy is approved. #65 is closed without merge;
  do not reopen or import its retired frontend dependency graph. Historical
  branch refs are not active work assignments.
- **Operations:** existing fictional setup validation, immutable receipts,
  preparation/retry, action-bound WebAuthn, inactive-school provisioning and
  scoped registry are implemented. The independent authenticated operator
  portal from #158 displays verified registry information but does not expose
  school creation, activation, grant, billing or integration mutations.
- **Database trust:** #148 adds direct PostgreSQL journal ACL audit coverage.
  It is not independent verification of calculated financial need, a full
  database role/RLS/indirect-access audit, or target-environment acceptance.
- **Governance and dependencies:** the
  [active main ruleset](https://github.com/Arete0920/Jirehfinancialaid/rules/27810515) requires PRs, strict current-head
  Python, Django, PostgreSQL and SonarCloud checks, with no bypass actors and
  zero required approving reviewers. Browser and dependency checks also passed
  but are not separately required by that ruleset. Independent human review
  is unavailable in the solo-maintainer path; do not imply human approval
  from automated checks. The current dependency audit reports 12 pinned
  packages, zero public OSV matches, and no missing or yanked hashes for the
  inspected pins. This does not establish absence of other vulnerabilities,
  repository security alerts, or licensing issues.
- **Packaging:** exact-source offline acceptance bundle construction exists
  and the browser run exercised extracted tracked source. The dedicated
  offline wheelhouse/release-bundle workflow did not run on this pinned SHA;
  obtain its own exact-SHA evidence before accepting an offline release package.
- **Not established:** approved hosting, deployed authenticated customer
  routes, actual runtime role topology/TLS/key management, monitored alerts,
  incident exercises, encrypted production backups and restore, institutional
  identity proofing, approved live methodology, or final release authorization.

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
| P0 | Standalone school/household/year identity | Unique annual draft; explicit grants; child selection; authenticated customer core and browser readback | Target-environment identity and tenant acceptance |
| P0 | Saved financial questionnaire | 31 approved development field paths, editable four financial sections, encrypted revision-bound fictional persistence, contributors and versioned school questions (#119, #122, #123, #127, #156) | Complete approved field/roster, consent, verification, retention and privacy policies; Q01–Q10 not fully resolved [#43](https://github.com/Arete0920/Jirehfinancialaid/issues/43) |
| P0 | Family-to-director journey | Guided browser demonstration and authenticated family/director portal; fixture questionnaire/documents/review routes; authenticated director API evidence (#155–#157) | Display existing `case.financial_evidence` in authenticated case HTML; verify full authenticated synthetic financial journey, including authorized decisions and readback without enabling live submission [#47](https://github.com/Arete0920/Jirehfinancialaid/issues/47) |
| P0 | Application review and final submission | Revision-bound review confirmation, readiness checks, fictional receipt; offline fee and submission validation; actual AidApplication model is DRAFT-only | Approve durable nonfinal lifecycle and consent/amendment policy; final SUBMITTED remains blocked until authoritative payment reconciliation [#45](https://github.com/Arete0920/Jirehfinancialaid/issues/45) |
| P1 | Financial documents | Scoped encrypted fictional upload/version/read/removal, audit, local ClamAV adapter (#97, #120, #156) | Approved production storage, scanning, key operations, retention, access and restore; real document collection remains disabled [#44](https://github.com/Arete0920/Jirehfinancialaid/issues/44) |
| P1 | Need and five buckets | Versioned five-bucket arithmetic, school-year plan, pinned fictional HUD allowance, saved-data need, dated changed income (#74, #132, #138–#147); #151 open | Approve methodology and school-specific category rules; distinguish preview from binding award; verify existing open PRs [#46](https://github.com/Arete0920/Jirehfinancialaid/issues/46) |
| P1 | Director decisions and reporting | Scoped workload and case readback; append-only fictional need decisions, budget reconciliation, contributor decision and changed-income evidence; #149 open | Unify authenticated readback and authorization with existing decision services; commercial award lifecycle and DB trust boundary [#47](https://github.com/Arete0920/Jirehfinancialaid/issues/47) |
| P1 | Onboarding and recovery | Grants, invitation dual proof, loopback SMTP, verified recovery foundations, director WebAuthn and authenticated sessions (#153–#155) | Institutional identity, real delivery, authorized onboarding, helpdesk and recovery acceptance [#49](https://github.com/Arete0920/Jirehfinancialaid/issues/49) |
| P1 | Independent operations | Setup validation, durable receipts, preparation/retry, inactive-school fictional provisioning, scoped registry and authenticated read-only operator portal (#131, #135, #158) | Authorized preparation/provisioning browser integration, activation policy, institutional onboarding and operational acceptance [#109](https://github.com/Arete0920/Jirehfinancialaid/issues/109) |
| P0 | Runtime and release packaging | Closed production URLConf; distinct guarded acceptance profiles; exact-source offline bundle builder and extracted-source browser verification | Complete reviewed prepayment acceptance profile, exact-release packaging evidence, hosting selection and deployment certification |
| P0 | Security and release | Seven current source checks passed; sanitized telemetry, readiness and direct-journal ACL audit | Verify the eleven target-environment D/T/S/M/I/A gates below [#48](https://github.com/Arete0920/Jirehfinancialaid/issues/48) |
| Deferred | Paid final submission / CompuWerx | $55 once per household fee and mandatory reconciliation contract | No provider-specific activity before separate owner authorization; paid commercial release remains blocked [#50](https://github.com/Arete0920/Jirehfinancialaid/issues/50) |
| Deferred | Partnerships, branding and exceptional multi-school use | Independent architecture and school-scoped identity; historical CROWN code is test-only reference | Optional SIS, approved configurable identity/branding and multi-school policy; do not make a CROWN dependency [#51](https://github.com/Arete0920/Jirehfinancialaid/issues/51) |

**No synthetic-only feature counts as customer-ready solely because its CI is
green.** Conversely, the eleven target-environment checks below are acceptance
gates, **not eleven failing source tests**. Record product completion, source
checks, target-environment acceptance, and actual business activation separately.

### Execution order

1. Reconcile the existing open PRs #149 and #151 against current protected main,
   respecting existing branch ownership. #149 and #157 share a functional area,
   not changed file paths; avoid duplicate assessment logic and new replacement
   PRs. Obtain fresh exact-head CI after synchronization.
2. Reuse the existing authenticated customer and independent operator
   interfaces, not a second set of financial or operations engines. Complete
   the authenticated director evidence display and integrated fictional
   family/review/director journey with negative authorization and revision tests.
   The expanded presenter demonstration remains a distinct acceptance decision,
   including owner-approved Jireh branding and manual pacing.
3. Reconcile unresolved product/privacy decisions in their existing issues
   (#43–#47, #49, #109); no inferred formula, consent policy, live storage,
   school activation or real account creation. Establish the database writer
   trust boundary and deployment design under #48.
4. Build the same prepayment application as a reproducible release candidate,
   verify the exact source/dependency package and complete synthetic target
   acceptance after approved hosting and operational configuration. Do not
   expose real financial data or enable final paid submission.
5. Obtain separate prepayment candidate acceptance. Begin CompuWerx work
   only after the owner separately authorizes that stage; verify the actual
   provider contract, server-side reconciliation and state transition before
   reconsidering commercial paid release.

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
