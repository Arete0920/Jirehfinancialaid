# Standalone Jireh production readiness — NO-GO

**Status:** NO-GO. **Scope:** `Arete0920/Jirehfinancialaid`, not CROWN.
**Latest exact-main source verification (2026-11-23):**
`e7dbfa885f19d3af6e959e4b4f2a6fd6c09a83dd` — six completed SUCCESS checks:
Python, Django, PostgreSQL 16, synthetic Chromium, SonarCloud and repository presentation.
[Foundation 45271109750](https://github.com/Arete0920/Jirehfinancialaid/actions/runs/45271109750),
[browser 45271109852](https://github.com/Arete0920/Jirehfinancialaid/actions/runs/45271109852),
[presentation 45271109797](https://github.com/Arete0920/Jirehfinancialaid/actions/runs/45271109797).
Historical snapshot statements below are updated where obsolete; this document remains **NO-GO**.
Keep `JIREH_OPERATOR_CREDENTIAL_RECOVERY_ENABLED` false,
the other privileged WebAuthn gates disabled, and customer routes unexposed.
This document does not authorize creating cloud resources, enabling runtime,
processing payments, collecting real family data, or initiating real recovery.

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
  Chromium [run 45271109852](https://github.com/Arete0920/Jirehfinancialaid/actions/runs/45271109852)
  concluded SUCCESS on this exact source SHA. The browser exercises fictional
  localhost workflows only, including the encrypted sample-PDF path; it is not
  a deployable customer browser, real upload or operational security PASS.
- **Parallel work (not merged or credited to main):** only feature
  [PR #65](https://github.com/Arete0920/Jirehfinancialaid/pull/65)
  remains open in the checked repository snapshot. It contains CROWN-derived
  officer wizard work and two unresolved authenticated SonarCloud SCA records.
  PRs #84, #86, #88, #89, #96, #97 and #98 are already merged and must not be
  counted as open or ported again. Recheck before acting.
- **Not established:** live hosting, deployed configuration, authenticated
  production APIs, database read isolation, observability, incident response,
  production backups, restore drills, real operator identity verification,
  WebAuthn hardware backup/counter policy, and security operations acceptance.

Passing source CI or a 200 from `/healthz/` or `/readyz/` is never a
production acceptance decision. The owner expressly defers CompuWerx activity;
$55 household submission must remain nonfinal until authoritative payment
reconciliation. No fake paid status, alternate processor or waived payment may
substitute for this mandatory future acceptance stage.

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
