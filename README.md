# Jireh Financial Aid

Jireh is being developed as an independent financial-aid product for **Christian and Catholic schools**.

**Engineering status:** Initial standalone Django school, household, student, annual aid draft and test-only authenticated API components, with migrations and regression tests. This is **not a deployable product**: real login/onboarding, end-to-end tenant isolation, secure financial-document storage, compliance controls, and payment processing remain incomplete. It is **not ready for customer use**.

## Approved product boundaries

- One financial-aid application fee of **$55 per household**, paid by the family, regardless of the number of children. Payment timing, refunds, and processing details are undecided; no payments are enabled.
- Five financial-aid buckets: need, mission, marketing/enrollment, merit, and hardship. This initial package defines their identifiers only; it does **not** implement financial need analysis or award decisions.
- Jireh SGO is excluded. CROWN and other student information systems may become optional integrations; none may be required for Jireh to operate.
- Hosting is not selected. No Azure services or deployment configuration are required or enabled.
- Real family/student information and credentials must never be committed to this public repository.

## Source preservation

The historical implementation remains in [`Arete0920/Crown-CSMS`](https://github.com/Arete0920/Crown-CSMS). The broad CROWN source copy in [retired PR #1](https://github.com/Arete0920/Jirehfinancialaid/pull/1) is a **migration reference, not a standalone application**. Do not merge that source copy wholesale. Transfer only reviewed, appropriately licensed components with validated standalone dependencies and regression coverage.

The five bucket identifiers follow `backend/financial_aid/models.py` in CROWN at source revision `ac9fab0981c281f9815b20160d37da4fa8e5bd1f`. The current repository's standalone contracts are independently tested; historic CROWN tests do not certify this product.

## Development checks

Python **3.12** is the initial supported test runtime. The original contract tests use only the standard library. School and household database tests use Django **5.2.18** (the exact version pinned in the current CROWN backend):

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m pip install --only-binary=:all: --require-hashes -r requirements.txt
PYTHONPATH=src python -m django makemigrations schools financial_aid --check --dry-run --settings=jireh.schools.test_settings
PYTHONPATH=src python -m django test jireh.schools jireh.financial_aid --settings=jireh.schools.test_settings
python -m compileall -q src tests
```

**Data boundary:** An academic year, household and student belong to one school. A student may be linked to more than one household (such as separated parents), but that relationship **does not grant access to another household's financial records**. The current `for_school` ORM helpers and school-checked linking service are internal safeguards, **not authentication or complete database-enforced tenant isolation**. A later authenticated API must enforce school and household authorization independently; no public or production endpoint is enabled by these models. Never use bulk or raw writes to bypass the link service.

All changes should use a narrow, reversible pull request (normally fewer than 20 changed files), targeted tests, and evidence for the exact commit. The product owner is a solo developer: automated checks and Copilot feedback are useful, but must not be misrepresented as independent human approval.

Commercial launch, hosting, live data, external integrations, and payment activation require separate approval and verified acceptance.


## Household access (test-only)

A signed-in Django user is **not automatically authorized** for a school, a
household, or every household sharing a child. An explicit active
`HouseholdAccess` grant is required for each household. Grants are keyed by
authenticated user ID (never email, HTTP headers or a student's relationships),
and access fails closed when the school, household, user or grant is inactive.

Two **read-only** GET routes, configured in the disposable
`jireh.schools.test_settings` URL routing, have negative HTTP tests:

- `/api/v1/schools/<school UUID>/households/<household UUID>/`
- `/api/v1/schools/<school UUID>/households/<household UUID>/students/`

These endpoints cannot grant access or change records. They have no public
registration or login endpoint and **are not deployed**. No production
settings, host authorization, HTTPS, public login, audited grant provisioning,
or secure financial records are available yet. Never deploy
`test_settings` or interpret passing SQLite tests as PostgreSQL-enforced
tenant isolation. Authenticated staff access and authorized grant provisioning
must be implemented and verified separately before commercial use.


## Annual household application draft (internal service only)

Jireh now has an independent `AidApplication` database model and an
authenticated `get_or_create_annual_draft` service. The database enforces at
most **one application per household, school and academic year**; all students
linked to that household share the application. A student may be associated
with two households, but these households have **separate applications and
access grants**.

The service requires an authenticated, active user with an explicit active
grant to the household and a matching school-specific academic year. A second
authorized member of the *same* household resumes the same draft rather than
creating another application. The original creator remains recorded.

Only **DRAFT** is implemented. No public application creation endpoint,
submission, appeal, financial income/document collection, payment, fee waiver,
refund or financial award decision has been enabled. A separate, reviewed
workflow must implement submission, consent, financial evidence and the
owner-approved $55 household fee contract before accepting any real families.


## School-staff aid inventory (test-only)

A new `SchoolStaffAccess` grant explicitly authorizes a user as an
`AID_DIRECTOR` at one active school. It does not imply a household grant,
general administrative access or permission at another school. No superuser
bypass exists for this prototype. Grant provisioning is internal/trusted:
there is no staff registration, invitation, role assignment or public write
endpoint.

The disposable test URL configuration provides one read-only GET route:

- `/api/v1/schools/<school UUID>/academic-years/<year UUID>/aid-applications/`

The handler requires an authenticated active user, an active director grant
at the requested active school, and a matching academic year. It returns
only draft application IDs, household IDs and status, capped at 100 rows
with `has_more` (pagination is **not yet implemented**). Anonymous access
returns HTTP 403; missing role, wrong school, revoked grants and nonexistent
resources return HTTP 404 without exposing school/customer information.

**Not deployable:** This is only a verified authorization prototype in
disposable Django test settings. Staff invitation, credential security,
staff permission review, pagination, financial data and authenticated
production API configuration are future separately reviewed work.


## Family annual draft HTTP (test-only)

The authenticated household draft service now has one **GET/POST** route in
disposable test settings:

- `/api/v1/schools/<school UUID>/households/<household UUID>/academic-years/<year UUID>/aid-application/draft/`

A verified, active household access grant is required on both methods.
**GET is read-only**, returning an existing draft or 404.
**POST creates or returns the same household/year draft**, using a Django
authenticated session and CSRF protection; its response is HTTP 200 whether
the existing draft is returned or a new one is created. POST without a valid
CSRF token is rejected. The GET route issues the CSRF cookie for a subsequent
authenticated request. No money is collected and no financial documents or
answers are accepted.

Tests explicitly cover separated-parent households, other schools,
revocation, unauthorized superusers, inactive identities and CSRF denial.
The endpoints are **not deployed** and must not be exposed through production
settings until secure login, session policy, grant provisioning, rate limits,
comprehensive auditing and PostgreSQL tenant/integrity tests are completed.


## Draft child selection (test-only)

A household's annual draft can include multiple children using the existing
`HouseholdStudent` association. Each selection has a protected FK to the
**specific household-student relationship**, not merely the child. A shared
child can therefore be selected independently by each authorized parent
household without linking their applications or financial information.

Two test-only routes extend the existing authenticated annual draft API:

- **GET** `.../aid-application/draft/students/` returns IDs for children
  selected in the authorized existing draft and sets a CSRF cookie.
- **POST** `.../aid-application/draft/students/<student UUID>/` includes that
  already-linked child idempotently, with CSRF validation.

Both require an active user, school, household grant and existing draft.
The child must be linked to that exact household and school. Wrong-school,
unlinked-child, unauthorized and revoked-access requests fail closed. No
application, new child, or household link is created implicitly. Selection
removal is deliberately **not implemented** pending an auditable edit
workflow.

The database enforces selection uniqueness and protects referenced household
links against ordinary deletes. **Cross-table school consistency is checked by
Django model/service validation, not by a complete database-enforced tenant
constraint**: raw SQL and bulk updates can bypass those checks. PostgreSQL
integrity testing, comprehensive auditing, secure login and full production authorization
remain prerequisites to handling real financial information.


## Minimal auditable draft mutations (internal and test-only)

Jireh now records two successful mutation facts in `AidAuditEvent`:
`DRAFT_CREATED` and `STUDENT_SELECTED`. Each includes the exact school,
application, authenticated actor, timestamp and (for student selection) the
specific application/household-child selection. There are **no financial
amounts, household answers, tax files, child names or free-text messages**
in this event model.

The existing authorized services create these events in the **same database
transaction** as the corresponding draft or selection. If an event cannot
be stored, the originating mutation is rolled back. Retries of the same
creation/selection do not create new events. The schema enforces at most one
event for each successful draft creation and for each selected child.

This is **not a comprehensive, tamper-proof audit trail**. Model instances
reject ordinary audit edits/deletions, but direct SQL, queryset updates and
privileged database access can bypass those restrictions. No denied-attempt,
read, role-grant, document, decision, payment, or deletion events are yet
covered. Independent PostgreSQL testing, database audit protections,
retention policy and operational monitoring are required before launch.


## Disposable PostgreSQL 16 verification (not a production deployment)

A dedicated GitHub Actions job runs Jireh's Django migrations and complete
test suite against a **temporary local PostgreSQL 16 container**, using
per-run, disposable CI-only credentials and a settings module that requires an explicit
CI guard. It uses the PostgreSQL driver version already pinned in CROWN.
The job requires the live database backend to be PostgreSQL 16; an SQLite
fallback or other PostgreSQL major version fails the job.

Additional PostgreSQL tests verify the database-backed annual uniqueness
constraint and a real second-connection `SELECT FOR UPDATE NOWAIT` lock.
The formerly expected-failing cross-table tenant-integrity tests are
now **required negative controls**: direct and bulk writes must reject
school/household mismatches in PostgreSQL. The CI job fails if tests
are marked as expected failures, and checks that the PostgreSQL-only
trigger migration is reversible and re-applies on a disposable database.

This job uses only disposable CI data and does not deploy or modify Azure
or any existing database. PostgreSQL validation is a prerequisite, but it
does not establish enterprise security, production availability, or
compliance certification.


### PostgreSQL relationship integrity (no production rollout)

Migration `financial_aid.0004_pg_tenant_triggers` adds **PostgreSQL-only**
table triggers enforcing relationships across household/student,
application/year/household, application/student-selection and audit-event
tables, even for direct queryset updates or bulk inserts that bypass
`full_clean`. School ownership of parent household/student/academic-year
records and established application/selection identities cannot be changed
in place. Audit event update/delete is blocked in ordinary SQL.

On SQLite, migration 0004 is intentionally a no-op: SQLite tests still
validate the service/model layer, but they do NOT certify database-level
cross-table enforcement. PostgreSQL CI verifies real raw/bulk denials,
expected-failure count zero, migrations, and forward/reverse replay.

**Limits:** These triggers are not PostgreSQL row-level security (RLS).
Privileged database roles may disable them; rollback/migration history must
be controlled. Existing data needs validation before any future production
migration. Access-control grants, operations audit, read restrictions,
customer authentication, hosting and sensitive-document management are
separate security requirements.


### Immutable access grants (not yet a provisioning workflow)

Migration `schools.0004_pg_grant_guards` blocks PostgreSQL UPDATE or
DELETE from silently changing the identity of an existing household or
school-staff grant. The protected identity includes the grant UUID,
creation timestamp, assigned user, household or school, and staff role.
Ordinary Django instance updates/deletes receive matching model-level
denials, including on SQLite. Grant revocation via `is_active=False`
continues to work; access queries immediately exclude inactive grants.

PostgreSQL CI exercises direct queryset reassignment, bulk deletion and
revocation, verifies both database triggers, and reverses/reapplies the
migration. The CI test command now uses shell `pipefail` so a failed
Django test run cannot be masked by the `tee` output command.

**This is not trusted identity provisioning or complete authorization.**
Existing grants can still have their active flag modified by privileged
database writers; grant creation and activation are not yet bound to a
verified, audited operator. PostgreSQL table owners can disable triggers;
SQLite has no database-level grant guard. A separately authorized grant
issuance, revocation/reactivation, audit, authentication and privilege
management design remains necessary before actual schools or families
are onboarded.

### PostgreSQL grant transition evidence (still not operator authorization)

PostgreSQL migration `schools.0005_grant_transition_events` records every
new household or school-staff grant and every **actual change** to its
`is_active` flag, including direct queryset/bulk updates. The grant UUID,
school UUID, scope UUID, target user ID, event type (created, revoked or
reactivated), new active status, database role and timestamp are stored in
`GrantTransitionEvent`. The event is written by an AFTER trigger **in the
same database transaction**; failed or rolled-back grant changes create no
committed event. An UPDATE that leaves `is_active` unchanged adds no event.

The event table is append-only under ordinary PostgreSQL UPDATE/DELETE.
Event reads are internal only; no family/staff route is exposed. SQLite has
the model but **no database transition capture**, so only PostgreSQL tests
certify this particular behavior. Existing grants are not backfilled.

**Important attribution limit:** `database_role` is the PostgreSQL login,
**not a verified human operator**. The current implementation still lacks
approved authority for issuing, revoking or reactivating grants; operators
with direct database access can perform those changes, and privileged table
owners can disable database triggers. This is transaction history evidence,
not a trusted provisioning workflow, RLS or launch authorization.

## Standalone runtime bootstrap (not deployed)

The separate `jireh.runtime` Django settings, WSGI/ASGI entries and root
`manage.py` establish a **fail-closed configuration foundation**. This is not
an approved public service, a customer demo or a complete authentication stack.
The runtime URL configuration exposes **only** `GET/HEAD /healthz/`: a
process-liveness response, **not** proof of database, financial-aid workflow,
provisioning or security readiness. Test-only family/staff API routes stay
in `jireh.schools.test_settings` and are not included in runtime routing.

Runtime startup requires explicit `JIREH_ENABLE_RUNTIME=1` and these values:

- `JIREH_SECRET_KEY`: an externally managed secret of at least 50 characters;
  never commit it or reuse the test secret.
- `JIREH_ALLOWED_HOSTS`: comma-separated exact hostnames/IP addresses; no
  wildcard, scheme, or port.
- `JIREH_DB_NAME`, `JIREH_DB_USER`, `JIREH_DB_PASSWORD`, `JIREH_DB_HOST`:
  PostgreSQL connection identity; optionally `JIREH_DB_PORT` (default 5432).
- `JIREH_DB_SSLROOTCERT`: an absolute path to an existing trusted CA PEM
  bundle. PostgreSQL connections use `sslmode=verify-full` and must verify the
  server's certificate and hostname. A file's presence alone does not verify
  its trust or the database connection.

The entrypoints force runtime settings; the disposable test settings are not
accepted as a runtime override. The hashed requirements now include the PostgreSQL 3.3.6 driver and
CPython 3.12 binary wheels. Deployment packaging, host-specific TLS
termination, operator authentication, secure grant management, financial forms,
submission and award decisions must still be verified before hosting.
`SECURE_SSL_REDIRECT` is enabled, but HSTS is deliberately disabled until a
real HTTPS origin is verified. Do not deploy on the strength of `check`, `/healthz/`
or CI alone; do not expose real family information or collect payments.

Configuration contract tests run in the lightweight Python job. The existing
PostgreSQL CI job also verifies the actual Django runtime settings and the
absence of family/staff routes without creating cloud resources.

## School-controlled household invitation foundation (not yet available to users)

The pending invitation data model and internal \`jireh.schools.invitations\` service
allow an explicitly authorized school aid director to issue and cancel invitations
**for active households at their own school only**. No Arete approval is needed
for routine school management.

- Each pending invitation contains a normalized recipient address, scope,
  24-hour expiration, authorized issuing director, and SHA-256 digest of a
  cryptographically generated 48-byte invitation secret. The raw secret is
  returned **once** to the trusted internal caller and is not persisted.
- Duplicate pending invitations to the same household/address are rejected.
  Expired invitations are revoked and audit-recorded before reissue.
- Issuance and cancellation write actor-attributed events transactionally;
  PostgreSQL guards immutable invitation identity and append-only audit rows.
- An invitation **never** confers household access by itself. Email addresses,
  including an existing account email, are not authentication or identity
  verification. No account activation, automated email delivery, public token
  redemption, or financial-data endpoints are enabled.
- These services are non-deployed foundations only. A future secure delivery
  and verified, authenticated one-time redemption flow must be separately
  implemented and reviewed before any family can use an invitation.

Do not log invitation secrets, use this module with real recipients, or treat
the presence of a pending invitation as authorization.


## Authenticated two-proof household redemption (internal-only)

The non-deployed \`jireh.schools.redemption\` service is a **foundation**, not
a complete onboarding or mailbox-verification product. A family member's
existing active, authenticated Django account must present **both** the
school director's invitation secret and a separate, 15-minute mailbox
challenge secret bound to that specific account and the invitation recipient
email. A stored account email, matching username, or invitation alone never
authorizes household access.

After verifying both secrets, the internal service atomically creates one
school/household-specific access grant, records the authenticated recipient,
marks the invitation and mailbox proof as used, and appends an actor-attributed
\`REDEEMED\` audit event. Failed audit persistence rolls everything back;
replay, revoked invitations, expired proofs, other accounts and cross-school
scopes are denied. Previously revoked access is **never** reactivated through
this path.

**Not implemented:** trusted email delivery, proven mailbox control, real
login/identity onboarding, CSRF-protected redemption endpoints, rate limiting,
public API exposure, or operational recovery. The proof-preparation service
returns a short-lived token to an internal trusted caller; only a separately
certified sender can deliver it to its bound address. Until such delivery
is certified, no real family should be invited or onboarded. Neither raw
secret is persisted. Runtime URL routing remains liveness-only.


## Optional authenticated SMTP delivery adapter (not activated)

The internal \`jireh.schools.delivery\` module adds **explicitly opt-in**
email sending for household invitation secrets and mailbox challenge proofs.
It requires the real Django SMTP backend, authenticated credentials,
STARTTLS on port 587 or implicit TLS on port 465, a remote SMTP host,
a dedicated sender, and a bounded network timeout. Delivery is disabled
unless \`JIREH_EMAIL_DELIVERY_ENABLED\` is explicitly set to boolean \`True\`
in an independently reviewed environment configuration. No such runtime
enablement, credentials, providers, or customer mailboxes are configured
by this change.

On successful SMTP submission the service returns only an invitation or
challenge ID to the trusted caller, never the raw token. A failed or
ambiguous send cancels the pending invitation with an actor audit or consumes
the undelivered challenge, so a retry cannot use the earlier code. SMTP
errors are sanitized rather than exposing provider responses or secret data.

**Security boundary:** SMTP acceptance does not prove human receipt, mailbox
ownership, or verified identity. The user must still authenticate and supply
both separately generated secrets to redeem an invitation. This adapter is
not a public route, login system, queue, delivery guarantee, rate limiter,
email-provider integration, or buyer-ready onboarding process. No real mail
should be sent until SMTP configuration and authenticated UI flow receive
separate approval and independent verification.


## Authenticated redemption HTTP prototype (disposable test settings only)

The \`jireh.schools.urls\` test URL configuration includes a **non-deployed**
redemption endpoint:
\`/api/v1/schools/<school UUID>/households/<household UUID>/invitation/redeem/\`.

An authenticated, active Django test session can GET to obtain a CSRF cookie.
POST requires that cookie's CSRF token and a bounded JSON object containing
exactly \`invitation_token\` and \`mailbox_token\` (both one-time 64-character
secrets). Invalid JSON, duplicate keys, unsupported methods, missing CSRF,
wrong account, revoked or used codes, wrong school and cross-household scope
fail without issuing a grant. Success returns only the household ID and
\`redeemed\` status; secret values are never returned. Responses are
non-cacheable, and the existing redemption service owns the atomic grant
and audit transaction.

**Explicitly not enabled:** \`jireh.runtime.urls\` still exposes liveness
only. The test endpoint is neither a public API nor a complete account login,
identity recovery, rate-limiting, CAPTCHA, abuse monitoring or production
onboarding solution. Do not route it into the deployable runtime before
authentication, operational rate limiting and provider-delivery controls
receive independent acceptance.


## Durable authenticated redemption attempt budget (test-only)

The disposable test-only household redemption POST endpoint now has a
**database-backed, account-wide** attempt budget: up to **10 authenticated
POST attempts per rolling-reset 15-minute window**. The budget is shared
across browser sessions and school/household URL parameters for the same
account; invalid credentials and malformed JSON count as attempts. Requests
beyond the limit return HTTP 429 with a Retry-After header and no grant.

The row stores only the authenticated user, window start and count — **no
tokens, email addresses, IP addresses, household identifiers or payloads**.
A database row lock on the user serializes attempt debits on PostgreSQL, and
a database constraint prevents counts above 10. The attempt is committed
before redeeming credentials, so a failed redemption cannot erase the debit.
An account's budget resets on its next request after 15 minutes.

**Not production-ready:** This prototype is not a global IP/network throttle,
CAPTCHA, distributed abuse monitor, incident logging system, lockout recovery
flow, or security-certified sign-in system. It must remain test-only until
trusted login, session policy, host-level protections and operations monitoring
are separately implemented and verified. The standalone runtime still routes
only \`/healthz/\`.


## Disposable family session sign-in and logout prototype (not deployed)

The **test-only** \`jireh.schools.urls\` configuration includes two
authentication routes: \`/test-auth/login/\` and \`/test-auth/logout/\`.
The login GET establishes a CSRF cookie; POST requires a valid CSRF
token and a bounded JSON object containing \`username\` and \`password\`.
The route delegates password checking to Django's configured authentication
backend. Invalid passwords, unknown accounts and inactive accounts receive
the same generic denial. On successful sign-in Django rotates the session
identifier and CSRF token; the new session expires within 15 minutes.
Logout is POST-only, CSRF protected and invalidates the caller's session.

A database-backed per-identifier budget allows at most **10 syntactically
valid login submissions per 15-minute window**, shared between sessions.
The identifier is stored only as an HMAC-SHA256 digest using Django's secret
key; passwords and raw usernames are never persisted in budget records.
A missing budget database fails closed. These controls do not replace
distributed IP/network enforcement, MFA, account recovery or credential
abuse monitoring. Limiting an identifier can itself allow targeted
denial-of-service; no customer-facing authentication is authorized until
those additional protections have been independently reviewed.

**No production exposure:** \`jireh.runtime.urls\` continues to expose only
\`/healthz/\`. Self-registration, account recovery, password reset,
external identity providers, live email, SMS, hosting, payments and
customer data remain out of scope. Tests use synthetic Django users only.


## Verified-contact password recovery foundation (internal-only)

A new **non-deployed** password-recovery service requires an account to
first enroll a recovery contact while authenticated, using a fresh,
account-bound 15-minute one-time mailbox challenge. Merely setting an email
on the Django user does **not** establish a recovery contact.

After this enrollment, an internal recovery request can send a separately
generated one-time 15-minute password reset code **only** to the verified
contact through the existing explicitly enabled, authenticated TLS SMTP
adapter. Unknown accounts, accounts without verified contacts, and blocked
requests return the same generic outcome. Only a SHA-256 digest of the
64-character reset secret is persisted; the raw code is never returned by
the request service. Reissue consumes the previous code, and a failed or
ambiguous send consumes the undelivered code. Both issuance and confirmation
have separate durable 10-per-15-minute attempt budgets backed by HMAC-only
account identifiers. Recovery confirmation validates the new password,
changes the Django password hash atomically and consumes the credential
with durable completion evidence. Changing the hash invalidates existing
authenticated sessions.

**Critical boundaries:** This is an *internal service* with no password
recovery HTTP endpoint, real SMTP configuration, public registration,
verified delivery certification, MFA, identity-support procedure, or
customer activation. Existing enrollment is deliberately immutable;
contact rotation requires a separately designed and verified workflow.
It must not be used for real user onboarding until these controls are
independently accepted. The standalone runtime remains liveness-only.


## Audited recovery-contact rotation (internal service; not deployed)

An authenticated family account may replace its verified recovery mailbox
only after presenting its **current password** and **two fresh, account-bound
mailbox codes**: one for the currently verified address and one for the
replacement. The one-time proofs must be distinct, unexpired and unconsumed.
Both are consumed atomically with the rotation. Older recovery contacts
remain in immutable history with a supersession timestamp; exactly one
current recovery contact per account is enforced by a database constraint.

Each successful rotation creates a protected event recording the authenticated
account, old and new contacts, and the authenticated actor. Any pending
password-recovery codes are consumed so the former address cannot reset the
password. Subsequent recovery messages are directed only to the new verified
contact. The prior contact and audit evidence cannot be deleted or rewritten
through the model API or PostgreSQL integrity guards.

**Not a public workflow:** No customer routes, provider configuration,
production secrets, or deployment are introduced. SMTP delivery remains
disabled by default. This service does not authorize a support agent,
school employee, or an attacker with only a session to rotate the contact;
production activation requires independent delivery, identity,
monitoring and account-recovery policy acceptance.


## Verified additional school aid directors (internal-only)

An **existing active aid director** may grant the same director role to an
additional existing active account in their own active school only after
that account has enrolled a **currently verified recovery contact**. Merely
populating the account's email field is insufficient. The issuing service
locks the school and rechecks the actor's authority before granting; the
subject account is locked and verified as active. It creates the grant and
an actor-attributed \`CREATED\` school decision in one transaction. If the
audit write fails, the privilege grant rolls back.

A given school/user pair may be issued only once. A revoked director grant
cannot be silently reactivated or recreated, and issuance never grants access
to other schools or households. Existing director revocation retains its
last-active-director protection and \`REVOKED\` audit events. Both actions
remain internal services, **not HTTP administration endpoints**.

**Initial director bootstrap is deliberately not implemented.** A school
with no authorized director cannot use this service. Real-world first
director assignment still requires a separately approved, strongly
authenticated provisioning process and operational certification. No
customer accounts, mail, cloud resources, payments, or CROWN dependencies
are activated by this change.


## First financial-aid director bootstrap (disabled-by-default, internal-only)

A school with **no historical director grant** may have an initial
financial-aid director proposed and approved only through an explicitly
enabled, internal two-operator procedure. Two distinct, individually
allowlisted, active staff-superuser accounts must each re-enter their
password. The proposed director must be an existing active nonprivileged
account with a verified recovery mailbox. Proposals expire after 15 minutes,
require a bounded external authorization reference, and do **not** grant
access at the proposal stage.

A second operator must independently confirm the school's external
authorization reference before invoking the approval service. Approval
rechecks school, subject, and operator eligibility, creates exactly one
school-specific grant, and records actor-attributed approval and grant
decision evidence in one transaction. An audit failure rolls back the
privilege grant. Even a **revoked** historical director grant blocks initial
bootstrap, preventing use as a privilege-restoration path. Expired proposals
may be closed and replaced without deleting their history.

The existing bounded authentication counter now provides a separate
**10 attempts per 15 minutes per allowlisted operator** budget for both
proposal and approval calls. Operator identifiers are HMAC-pseudonymized
and never stored in plaintext. The debit is committed before the
grant-issuing transaction, so rejected passwords cannot refund an attempt.
Missing database storage and rollback-capable outer transactions fail closed.
This does not replace phishing-resistant operator MFA, institutional
authorization, secure enrollment/recovery or abuse monitoring; those
remain requirements before any real operation.

**Not enabled or deployed:** The bootstrap setting defaults to disabled
and no operator IDs are configured by runtime settings. The service is not
an HTTP endpoint, a customer onboarding workflow, a school creator, or
proof of institutional approval by itself. External institutional approval,
operator identity management, secret storage, and production certification
must precede any real provisioning. No real school, account, or cloud
resource is modified by this feature.



## Internal WebAuthn operator assertion verifier (not activated)

The internal-only `jireh.schools.operator_webauthn` module provides an
isolated WebAuthn assertion verifier using Yubico `python-fido2==2.2.1`,
with hash-pinned **Ubuntu 24.04/Python 3.12 CI-only** dependencies in
`requirements-webauthn-ci.txt`. Synthetic signing-key tests cover successful
signature verification and negative controls for origin, challenge, relying
party, credential identity, user verification, cross-origin assertions and
non-increasing signature counters. No custom signature cryptography is used.

The verifier requires an exact lowercase HTTPS relying-party origin, a
trusted previously enrolled credential, required user verification and an
advancing positive signature counter. Authenticators that do not advance
counters are deliberately unsupported by this initial contract.

**Do not activate for real operators.** There is no verified registration
workflow, trusted attestation/enrollment store, persistent operator-key
binding, durable single-use challenge store, expiration or atomic signature
counter update; therefore full replay prevention is **not established**.
Nor is there a password-plus-FIDO2 gate, operator session, privileged action
authorization, recovery policy, UI or public endpoint. Bootstrap remains
disabled by default and is not wired to this verifier. Production packaging
(including Windows/macOS), identity authorization and complete end-to-end
security testing require separate acceptance.



### Durable WebAuthn challenge lifecycle (internal-only, inactive)

The separate `operator_webauthn_challenges` service maintains a PostgreSQL-
guarded, five-minute, one-use assertion challenge bound to one allowlisted
operator, exact HTTPS RP/origin, and enrolled credential fingerprint. It
serializes calls on the operator row, closes expired or rejected challenges,
and prevents challenge reuse. Invalid cryptographic assertions consume the
pending challenge rather than returning a privilege or session. The feature
flag `JIREH_OPERATOR_WEBAUTHN_CHALLENGES_ENABLED` is **false by default**.
This module has no HTTP route and is not called by first-director bootstrap.

**Explicit limitations:** The caller must already authenticate the operator
and supply a trusted enrolled credential. There is no certified enrollment
or credential registry, no atomic long-term signature-counter update, no
operator session, no password-plus-FIDO2 enforcement, no real-world MFA
activation and no production packaging acceptance. The returned counter
is evidence for a future registry, NOT authorization. A legitimate
authenticator must not be given privileges until the complete integrated
transaction and recovery flow have been independently verified.

### Internal operator credential registry (not activated)

The `OperatorWebAuthnCredential` registry stores a bound WebAuthn public key,
credential-ID digest, relying-party origin, a nullable independently verified
enrollment timestamp, a persistent signature counter, and irreversible
revocation evidence. PostgreSQL guards enforce immutable credential identity
and key material, non-regressing counters, and one-way revocation. An unverified
or revoked credential cannot be used through the new registry-backed service.

`operator_webauthn_registry` issues challenges only from an **already verified,
active registry record**. It consumes the challenge and writes the resulting
counter in the same durable transaction, serializing access to the operator
and credential records. Rejected signatures consume the challenge but do not
advance the counter. This service returns a counter, **not authentication or
authorization**. Existing prototype helpers remain internal and must never be
connected to privileged or public paths.

**Enrollment is not implemented:** `enrollment_verified_at` is deliberately
nullable. Only synthetic tests insert verified registry records. There is no
real attestation/registration ceremony, enrollment approval, trusted registrar,
credential recovery, full authenticator policy, protected operator session, or
password-plus-FIDO2 integration. The operator challenge feature remains
disabled by default; no customer accounts or production resources are touched.
The strict-increasing-counter prototype intentionally excludes devices that
always return zero. A documented backup-state and counter policy is still
required before production rollout.

### Internal WebAuthn registration ceremony (inactive, pending-only)

The `operator_webauthn_registration` service adds a five-minute,
operator-bound and one-use registration ceremony. The Yubico FIDO2 server
checks the exact relying-party origin, challenge, user presence, user
verification and registration data. Rejected/expired submissions are
consumed, and the protected PostgreSQL journal forbids reopening history.
New public keys are stored **unverified** (`enrollment_verified_at=NULL`).
The ceremony requires `JIREH_OPERATOR_WEBAUTHN_REGISTRATION_ENABLED=True`
as well as the existing internal challenge feature flag; both are disabled
by default. No public URL or production deployment enables them.

**Security boundary:** WebAuthn registration with attestation `none` is
not evidence of independently verified operator identity, trusted device
provenance or an approved institutional enrollment. It cannot mark a
credential verified; an additional independently authorized identity
verification and proof-of-possession workflow must be built and accepted
before keys are enabled. No authenticated session, school role or privileged
bootstrap decision is granted. Synthetic tests are not a production
registration certification.

### Pending WebAuthn credential proof of possession (internal-only)

The disabled-by-default `operator_webauthn_possession` service offers a
five-minute one-use assertion challenge for an **unverified** operator public
key already registered by the pending enrollment ceremony. Successful
cryptographic verification records an immutable proof event and atomically
advances the key's monotonic signature counter; failed or expired attempts
consume the challenge without issuing evidence. PostgreSQL guards prohibit
reopening, rewriting or deleting completed proof events.

`JIREH_OPERATOR_WEBAUTHN_POSSESSION_ENABLED` defaults to **false**.
The existing internal challenge gate and operator allowlist must also be
explicitly active. There is **no public URL, session, MFA approval, live
identity attestation or school-role grant**. Critically, a successful proof
**does not change `enrollment_verified_at`**; a separate institutionally
authorized identity and enrollment approval process remains mandatory.
This prototype intentionally excludes authenticators with non-increasing
signature counters until a reviewed backup/counter policy exists.

### Owner or integration manager credential approval (internal, disabled)

The internal `operator_webauthn_approval` service provides the final,
explicit, human-authorized **credential enrollment** step. Only configured,
distinct, active Jireh superuser identities in
`JIREH_ENROLLMENT_OWNER_USER_ID` and `JIREH_ENROLLMENT_MANAGER_USER_ID`
may act as owner or integration manager respectively. The separate
`JIREH_OPERATOR_ENROLLMENT_APPROVAL_ENABLED` gate is false by default.
Approvers must re-enter their own current password, are subject to
the existing durable operator-attempt budget, and cannot approve their
own credentials.

An owner or integration manager must independently verify the prospective
operator's identity and authorization **outside the application** before
submitting a bounded external identity-verification reference. The service
requires an existing closed registration, a fresh successful cryptographic
proof-of-possession record for that exact key, a matching stored counter,
and an unrevoked, still-unverified credential. The approval and credential
activation commit atomically. An append-only, role-attributed approval
record identifies who approved whom, the registration, possession proof,
reference, and approval time. PostgreSQL rejects SQL modification/deletion
of recorded approvals.

**Limits:** a reference is evidence of the designated human's attestation,
not automatic identity verification. No identity service, authenticated
operator console, credential recovery, real operator provisioning, or
WebAuthn MFA enforcement for first-director bootstrap is created. The
other underlying WebAuthn feature flags remain disabled. No production
credentials are enrolled or activated by this code change.

### Database credential-activation evidence guard (internal only)

PostgreSQL migration `schools.0020` denies inserting an already verified
WebAuthn credential and rejects every initial `enrollment_verified_at`
transition unless an exact, previously recorded owner/integration-manager
approval exists for the **same** credential, operator and approval timestamp.
The original immutable-key and non-revocation guards remain enforced.
Direct Django `QuerySet.update()` and SQL cannot bypass this new audit
requirement through ordinary application database credentials. The gate does
not independently authenticate the human approver: that remains the
responsibility of the disabled-by-default approval service and a separately
validated real-world identity-verification procedure. Existing synthetic
registry tests create matching synthetic audit and possession evidence.
No production MFA is enabled.


### Mandatory action-bound WebAuthn for first-director bootstrap (internal-only)

The `operator_webauthn_actions` service creates a one-use evidence record
for a specific **first-director proposal or approval**, hashing the canonical
action type, exact school/subject or request ID and authorization reference
before exposing a WebAuthn challenge. Only a verified, active registered
operator key may sign the challenge. Mismatched action context, expired
or unverified assertions, revoked credentials, and consumed records are
rejected. PostgreSQL prevents raw rewrites, replay and deletion of evidence.
Both first-director proposal and independent approval now require the
exact operator's fresh, action-matched proof, consumed in the **same database
transaction** as proposal/grant creation. A wrong school, subject, request,
authorization reference, operator, revoked key, expired assertion or already
consumed proof fails closed. The original password and attempt-budget checks
and two-distinct-operator requirement remain in force. If either the action
MFA flag or the bootstrap feature is disabled, no grant can proceed.

`JIREH_OPERATOR_ACTION_MFA_ENABLED` and
`JIREH_FIRST_DIRECTOR_BOOTSTRAP_ENABLED` both default to false. This code
has **no live operator console, public endpoints or production acceptance**.
Human identity verification, real credential onboarding, recovery and
hardware backup-state policy are still required before real-school use.
Synthetic cryptographic integration tests exercise both operator signatures,
wrong scope, replay, revocation, and transactional rollback. A verified proof
does not itself grant login or an operator session.

### Independent operator WebAuthn lost-key recovery (internal, disabled)

The recovery service uses a separate default-OFF gate,
`JIREH_OPERATOR_CREDENTIAL_RECOVERY_ENABLED`. The explicitly configured
owner or integration manager must independently check the affected
operator's identity and institutional authority, supply a recorded
verification reference, and reauthenticate with their own password.
Self-recovery, unconfigured authorities and already revoked credentials
are rejected. Owner/manager attempts consume the existing durable
privileged-operation attempt budget.

An approved LOST/COMPROMISED recovery **revokes the old verified
credential permanently**, preserving an immutable, independent recovery
audit record in the same durable transaction. An inactive affected
operator's credential can still be revoked. All normal WebAuthn assertions
and privileged actions fail closed for revoked credentials.

Replacement cannot reactivate the old credential or bypass enrollment.
It must be a **different credential registered after the recovery**,
bound to the same operator and RP/origin, with successful WebAuthn proof
of possession and independently authorized owner/manager approval through
the ordinary credential-approval service. Separate recovery confirmation
then records an immutable linkage without granting any new privilege.
PostgreSQL protects both recovery and confirmation records from mutation
and deletion and verifies their credential/evidence relationships.

**Not production ready:** Real-world identity and institutional authority
verification remains a human responsibility outside Jireh. No operator
recovery UI, authenticated session, public endpoint, incident notification,
live credential onboarding, backup-authenticator policy, or production
deployment is created or enabled. Neither owner nor manager IDs are
configured here. All verification uses synthetic keys and identities.
