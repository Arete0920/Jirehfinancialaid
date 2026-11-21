# Jireh Financial Aid

This repository is a separate working copy of the CROWN CSMS source baseline
for developing the Jireh Financial Aid solution. It preserves shared application
code and existing Jireh work so development can continue without rebuilding
from scratch. The source repository is unchanged.

## Starting point

The initial source baseline was copied from
[`Arete0920/Crown-CSMS`](https://github.com/Arete0920/Crown-CSMS) at commit
`ac9fab0981c281f9815b20160d37da4fa8e5bd1f` (2026-11-21). This is intentionally
a broad baseline, not a completed extraction: Jireh's application workflows
currently depend on CROWN's shared identity, authorization, tenant, aid, and
financial services. Other CROWN modules remain in this repository until those
dependencies can be separated and validated safely.

The source migration omitted GitHub Actions workflows, agent instructions,
Crown-specific editor tasks, operational audit/runtime evidence, and a
checked-in private key. No credentials, local databases, or deployment workflow
were copied.

## Jireh source inventory

The following paths are present in this baseline. Presence is not evidence of
standalone or production readiness.

| Area | Source and boundaries |
| --- | --- |
| Website and assets | [`sites/jireh`](sites/jireh/) contains the site, SGO logo, family-billing image, overview PDF, and site tests. The site also uses [`sites/shared/product-theme.css`](sites/shared/product-theme.css). |
| School aid | [`backend/aid`](backend/aid/), [`backend/financial_aid`](backend/financial_aid/), the [family preparation page](frontend/dashboards/src/pages/ParentFinancialAidPreparationPage.jsx), and [decision page](frontend/dashboards/src/pages/JirehAidDecisionsPage.jsx) retain existing application and review work. These are not a claim that both aid implementations are interchangeable. |
| Wizard and dashboard | The [aid wizard](frontend/dashboards/src/pages/FinancialAidWizard.jsx), [wizard steps](frontend/dashboards/src/pages/financial_aid_wizard/), [dashboard](frontend/dashboards/src/pages/FinancialAidDashboard.jsx), and [dashboard template](frontend/dashboards/src/config/dashboardTemplates/financialAidDashboard.js) remain embedded in the shared CROWN shell. Illustrative template metrics are withheld by the dashboard page; runtime data must be verified separately. |
| SGO pilot | [`backend/jireh_sgo`](backend/jireh_sgo/) and the SGO dashboard, login, and intake pages are separate pilot work, not an accepted production scholarship or funds-processing service. See the [fictional intake boundary](docs/jireh-sgo-fictional-intake.md). |
| Tests | Existing targeted backend, frontend, site, and browser tests accompany the copied work. See the [local presenter boundary](docs/sandbox/UNIVERSAL_JIREH.md) for what the fictional aid journey does and does not prove. |

On 2026-11-21, a source comparison of these backend directories, dashboard
pages and template, Jireh site, and shared theme found no content differences
from the pinned CROWN revision, ignoring line endings. This is not a full
asset census: external designs, prior history, and other branches must be
reviewed separately. A targeted search of open CROWN pull requests did not
identify a Jireh-titled open PR; it is not an exhaustive branch comparison.

### Local baseline assessment

On 2026-11-21, using application source at Jireh commit
`48e0fb5965c975a2b5dcb744d9023163dae5891c`:

- The Jireh site tests passed (5 tests); the dashboard frontend build and
  eight focused aid/SGO frontend test files passed (85 tests).
- Django system and migration checks passed. The focused fictional presenter,
  aid authorization/award, and SGO intake API suite passed (31 tests and
  17 subtests), including submission, review, a noncash credit, SGO correction,
  and access checks on an isolated test database.
- In the isolated Heritage local demo, the existing Chromium tests passed
  (2 tests): a fictional parent submitted school aid and saw it after a browser
  reload, and the test found no `actual_income` input or file-upload field.
  This browser rehearsal does not prove browser-based review, approval,
  renewal, or SGO.

These are local results, not independent review, hosted acceptance, or proof
that a complete customer aid cycle is ready to sell. The demo uses CROWN
fixtures and adapters; it is not an independently operated Jireh installation.

## Standalone and commercial boundary

Jireh must work without a running CROWN installation before it can be offered as
an independent product. Its school, user, family, student, financial and audit
dependencies, customer journeys, permissions, reporting, onboarding, recovery,
privacy and operational controls require assessment and acceptance. Any future
CROWN integration needs agreed ownership and synchronization rules; it must
remain optional. School-aid and SGO authority must remain distinct.

Fictional local tests and a copied interface do not authorize real customer
data, hosted activation, financial settlement or a commercial release. The
owner must approve the product scope, relevant controls and deployment plan
before those activities. Azure remains deferred.

## Development

Start with the [engineering setup guide](docs/engineering/DEV_SETUP.md) for
the supported toolchain, backend and frontend commands, and local development
instructions. For the Jireh product boundaries and current capabilities, see
the [Jireh website migration guide](docs/operations/JIREH_FAMILY_WEBSITE_MIGRATION_20261015.md)
and [Jireh site README](sites/jireh/README.md).

For a separate ChatGPT/Codex session, start with the
[Jireh ChatGPT/Codex handoff](docs/engineering/JIREH_CHATGPT_CODEX_HANDOFF.md).

## Hosting and release status

Azure credentials, connections, resources, and deployment workflows have not
been configured for this repository. No deployment, DNS change, live financial
processing, or production access is authorized by this source copy. Treat any
future infrastructure setup or release as a separate, explicitly reviewed
change.

The retained website preflight requires an explicitly named resource group and
rejects the historical `crown-rg` target. A different name alone does not prove
isolation, cost approval, or permission to provision. Historical CROWN website
deployment instructions are not an execution path for this repository. The
repository owner is the decision owner for a separately reviewed Jireh staging
proposal and its costs.

The preflight isolation change is based on Jireh commit
`c13c48d2c80c693b7447510c62379eadb5766b51`. If it must be reverted, revert the
change together with its tests and documentation; do not use the historical
CROWN defaults or workflow to deploy. Standalone operation, Azure resource
isolation, hosted acceptance, backup/restore, and production readiness remain
NOT VERIFIED.

Source availability and automated checks do not establish that a feature or
hosted environment is ready for release. See [SECURITY.md](SECURITY.md) for
security reporting information and the repository's inherited [NOTICE.md](NOTICE.md)
for ownership and rights information.
