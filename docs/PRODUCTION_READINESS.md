# Standalone Jireh production readiness — NO-GO

**Status:** NO-GO. **Scope:** `Arete0920/Jirehfinancialaid`, not CROWN.
**Source/CI baseline verified:** `e7dbfa885f19d3af6e959e4b4f2a6fd6c09a83dd`
(2026-11-23; GitHub protected `main`).
Keep `JIREH_OPERATOR_CREDENTIAL_RECOVERY_ENABLED` false,
the other privileged WebAuthn gates disabled, and customer routes unexposed.
This document does not authorize creating cloud resources, enabling runtime,
processing payments, collecting real family data, or initiating real recovery.

## Evidence classification

- **Source/CI evidence (verified):** protected `main` commit
  `e7dbfa885f19d3af6e959e4b4f2a6fd6c09a83dd` has **six completed,
  successful exact-SHA checks**: Python 3.12 contracts/repository hygiene;
  Django 5.2 school/household tests; PostgreSQL 16 migrations/integrity;
  SonarCloud code analysis; repository presentation/attribution; and
  synthetic localhost Chromium browser E2E.
  [Foundation run 45271109750](https://github.com/Arete0920/Jirehfinancialaid/actions/runs/45271109750),
  [presentation run 45271109797](https://github.com/Arete0920/Jirehfinancialaid/actions/runs/45271109797),
  and [browser run 45271109852](https://github.com/Arete0920/Jirehfinancialaid/actions/runs/45271109852)
  completed successfully on that commit. They certify neither hosted runtime
  acceptance nor operation with real customer data.
- **Synthetic tenant acceptance (verified as test coverage, not production):**
  `src/jireh/financial_aid/test_tenant_http_acceptance.py` is included in
  the Django/PostgreSQL source test suite. It exercises synthetic authenticated
  sessions, two-school denials, separated households sharing a child, revoked
  grants, CSRF and nonmutation. A green aggregate suite establishes that
  its included tests did not fail; it is not evidence of deployed tenant
  isolation or approved live authentication.
- **Standalone runtime exposure (source only):** `src/jireh/runtime/urls.py`
  exposes only `GET/HEAD /healthz/` for liveness and `GET/HEAD /readyz/`
  for a read-only database connectivity probe. The latter returns generic
  HTTP 503 on a failed database check, not SQL or credential details.
  Request correlation IDs and bounded, sanitized server-side request events
  are a source logging foundation, **not** verified alert delivery or an
  accepted operations deployment. Test/demo financial-aid, login and staff
  routes remain in a separate URLConf; no hosted runtime is accepted.
- **Browser acceptance scope:** the synthetic localhost Chromium workflow
  [45271109852](https://github.com/Arete0920/Jirehfinancialaid/actions/runs/45271109852)
  completed successfully on exact protected `main`
  `e7dbfa885f19d3af6e959e4b4f2a6fd6c09a83dd`. This closes the
  prior exact-main browser evidence gap **for synthetic tests only**; it is
  not deployed browser acceptance, real-school onboarding or payment evidence.
- **Parallel work (not merged or credited to main):** at this checkpoint
  the only open PR is [#65](https://github.com/Arete0920/Jirehfinancialaid/pull/65)
  (CROWN wizard primitives). Its two unresolved SonarCloud SCA dependency-risk
  records prevent treating the PR as accepted or its frontend as released.
  Recheck live PR state before subsequent decisions.
- **Payment and first-client acceptance:** the owner approved **$55
  family-paid per household annual application**, initiated at proposed
  submission, but final `SUBMITTED` status and award-queue entry require
  trusted server-side payment verification. No payment initiation, callback,
  settlement or paid final submission is active. Under the owner's
  [November 23 provider hold](https://github.com/Arete0920/Jirehfinancialaid/issues/50#issuecomment-7103729979),
  all CompuWerx-specific activity is deferred pending a clean independent
  candidate and separate authorization. The paid first-client transaction
  gate is **BLOCKED — provider stage deferred by owner**. A nonpayment
  release candidate can be tested without claiming this gate passed.
- **Not established:** approved hosting and its configuration, authenticated
  live customer routes, deployed tenant read isolation, alert delivery and
  monitoring operations, incident response drills, backups/restores, real
  operator identity verification, authenticator recovery/counter policy, and
  operations/security acceptance.

Passing a unit/integration suite or a 200 from `/healthz/` is never a
production acceptance decision.

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

## Commercial transaction gate (additional to the 11 operations/security gates)

**Disposition: BLOCKED — provider stage deferred by owner.** The December 1,
2026 first-client target does not override the latest owner hold or authorize
unverified payments. The approved policy requires one $55 family-paid fee
per household annual application, initiated at submission; the application
must remain pending until correct, authoritative server-side confirmation.
A checkout initiation, client response or asserted callback is not proof
of payment. No unpaid-submission bypass, invented paid state, default waiver
or substitute processor is approved. Merchant, refund, waiver, chargeback
and multi-school treatment are unresolved. The independently buildable
**nonpayment release candidate** and a **paid first-client launch GO** are
different decisions. [Owner decision and hold](https://github.com/Arete0920/Jirehfinancialaid/issues/50#issuecomment-7103729979).

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

**NO-GO** for customer use until every applicable operational gate has immutable
PASS evidence and designated human approval, and the first-client payment gate
has independently verified acceptance following separate provider-stage
and release authorizations. The candidate test suite and this runbook are
development artifacts only. No automatic GO is implied by merging or passing CI.
