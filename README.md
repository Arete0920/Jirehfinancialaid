# Jireh Financial Aid

Jireh is being developed as an independent financial-aid product for **Christian and Catholic schools**.

**Engineering status:** Initial standalone Django school, academic-year, household and student models, migrations, and tests. This is a **data-domain foundation only**: there is no authenticated application, public API, proven end-to-end tenant isolation, secure financial-document storage, or payment processing. It is **not ready for customer use**.

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
python -m pip install -r requirements.txt
PYTHONPATH=src python -m django makemigrations schools --check --dry-run --settings=jireh.schools.test_settings
PYTHONPATH=src python -m django test jireh.schools --settings=jireh.schools.test_settings
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
settings, host authorization, HTTPS, CSRF-protected write workflow, school staff
authorization, or secure financial records are available yet. Never deploy
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
