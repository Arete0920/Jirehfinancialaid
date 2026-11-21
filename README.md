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
accepted as a runtime override. The runtime requires a compatible PostgreSQL
Python driver, and that driver, deployment packaging, host-specific TLS
termination, operator authentication, secure grant management, financial forms,
submission and award decisions must be verified separately before hosting.
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
