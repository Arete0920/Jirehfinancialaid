# Jireh Financial Aid — Azure staging candidate (NOT DEPLOYED)

This is a retained CROWN-era website candidate, not an approved standalone
Jireh release. The current product scope is school financial aid only; SGO is
excluded. Existing SGO content and assets are historical and must be reviewed
before any future website release.

- Primary: CROWN Jireh mission-aligned school financial aid.
- Historical pilot-development content: Jireh SGO scholarship-grantor administration.
- Site source: `sites/jireh/index.html`
- Shared family-wide appearance: `sites/shared/product-theme.css`
- Built output: `sites/jireh/dist/` (generated; do not commit)
- **No Azure deployment, paid service or GoDaddy DNS change is authorized by this PR.**

## Build and test

```bash
node --test sites/jireh/tests/site.test.mjs
node sites/jireh/build.mjs
python3 -m http.server 8090 --directory sites/jireh/dist
```

Azure Static Web Apps build configuration when Azure inventory/budget approval and a deploy plan exist:

- app_location: `sites/jireh`
- app_build_command: `node build.mjs`
- output_location: `dist`
- api_location: unset (no demo registration API has been accepted)
- default domain until DNS/CNAME prevalidation and cost approval

## Migration source and uncompleted dependency list

Original site sources:
- https://areteadvisorygroup.com/jireh
- https://areteadvisorygroup.com/jireh-sgo
- https://areteadvisorygroup.com/resources/jireh-sgo-overview.pdf
- https://areteadvisorygroup.com/images/jireh-sgo/logo.png

The staged build serves the overview PDF and product imagery from the committed local assets described below. Legal links and contact requests still point to the existing Arete website. Independently test those link targets and the deployed asset bytes before main-site retirement.

The first-party lead/demo registration service is NOT implemented or certified; existing contact CTA is a transitional handoff, not a guaranteed booking. Confirm end-to-end persistence, acknowledgment, sales routing, calendar booking, consent, abuse prevention and fault recovery before claiming instant scheduling.

Required gates: read-only authenticated Azure subscription/RBAC/spend/alerts/quotas/resource inventory, GoDaddy authoritative DNS and email record export, security and audit review, source-asset ownership, functional QA, accessible desktop/mobile/browser verification, staging TLS, cost approval, and tested reversible single-hostname cutover. Do not conflate production-ready marketing with production-ready financial-aid processing.

## Exported source assets

The SGO PDF, the official SGO logo, and the CROWN family billing concept image are in the site source and copied into the staging output by `build.mjs`. Confirm owner rights and visual parity in browser QA; `https://areteadvisorygroup.com/contact`, privacy and terms remain live links for the transition.

The October 18 pilot overview is a newly authored typographic document built by `python sites/jireh/build-overview.py` using the locked backend ReportLab dependency. It replaces the imported October 8 brochure; the original and its intact authenticity records remain at commit `b5ccf6102a1bdc786e2348d58d2844d70256a810`. The builder does not modify the original or use its embedded media. Pilot status, grantor responsibilities, and operational acceptance requirements remain explicit. Review all rendered pages and update the exact binary admission in `scripts/ci/repository_identity_hygiene.py` after an intentional rebuild.


## Historical CROWN hosting evidence (15 Oct 2026)

**Historical reference only:** The CROWN workflow described below was not copied
into this repository. Its prior approvals, CROWN resource group, and historical
run are not authorization or evidence for a Jireh deployment. Azure resources,
connections, and deployment remain deferred. Any future Jireh staging requires
separate owner approval and a reviewed Jireh-specific workflow and resource
isolation. `scripts/ops/jireh_azure_site_preflight.py` is a read-only collector,
not a deployment workflow; it cannot establish resource isolation or authorize
provisioning.

## Evidence collected from 12 Oct 2026 manual run

- GitHub Actions run 38247725456 authenticated successfully using federated Azure login and completed the resource-inventory collector.
- The owner subscription's `crown-rg` contained 26 Azure resources, including **one Static Web App** already assigned to CROWN's dashboard and existing production App Service infrastructure.
- Azure cost diagnostics returned **UNAVAILABLE/RATE_LIMIT** for month-to-date and last-month charges, and **UNAVAILABLE/AUTHENTICATION** on one budgets operation. **Do not interpret missing costs as $0 or proof of free eligibility.**
- The hosted production API health check answered HTTP 200 with database reported OK, but was not exact-head release parity for the Jireh website.
- Production CROWN runtime certification remained `NOT VERIFIED`; none of the historical preflight evidence authorizes payments, student financial data or a public Jireh portal.

## Historical gated operations — superseded for Jireh

1. Establish a separately reviewed Jireh-specific preflight and workflow when the owner authorizes that work. The historical CROWN workflow is not present here. Treat unavailable evidence as blocked.
2. In Azure Portal Cost Management (authenticated owner), confirm actual current and last month costs, subscription budgets, alert recipients, and eligibility for an additional **Free** Azure Static Web App (and any feature/quota restrictions). The current Free listing alone is not a sufficient approval.
3. Only after explicit approval of recurring charges, authorize a new isolated Jireh *staging* Static Web App. **Do not repurpose `crown-dash` or attach a new product site to its live resources.** Deploy only the committed `sites/jireh/dist` build to the Azure-assigned temporary hostname; disable search indexing.
4. Validate TLS, security headers, 320/375/768/1440px browser appearance, internal links, robots and CTA handling with seeded *synthetic* data; verify actual inquiry notification and persistence through Arete's existing contact workflow or a separately accepted registration backend.
5. Export the authoritative DNS zone and confirm who currently controls website hosting, domain, and email. Preserve existing MX, SPF, DKIM, DMARC and verification TXT records.
6. Choose the Jireh hostname, complete TXT/CNAME ownership verification, rehearse reversible DNS-only switch, and take formal launch approval. After confirmed live stability update Arete site links and condense duplicate content while retaining advisory articles.

**No public launch, resource provision, billable tier or DNS changes are authorized by this document.** No GitHub artifact substitutes for the owner's billing view or tested staging.


## Historical CROWN one-shot staging proposal — not authorized here

The following describes the prior CROWN proposal, not an available or authorized
Jireh execution path. Its trigger must not be used as approval.

- Source: accepted main commit only; Jireh site built and local tests pass before modifying Azure.
- Authentication: existing GitHub Actions OIDC federation, no new client secret.
- Target: `crown-rg/jireh-site` in East US 2, SKU **Free only**, on an Azure-generated temporary `azurestaticapps.net` hostname.
- Before creation: validate the whole subscription's SWA inventory, recognized SKUs, ownership, and official 10-Free-sites subscription limit; refuse unknown or exhausted quota, paid existing instances, or conflicting ownership.
- After creation: validate returned SKU remains Free. Never operate on `crown-dash` or CROWN production API.
- Deployment uses an ephemeral masked SWA deployment token. No account IDs or tokens go to repository or GitHub artifacts.
- Release proof: HTTPS content, robots noindex, PDF, logo, and concept image bytes exactly match the committed source.
- No custom domain assignment, DNS update, GoDaddy record alteration, live payments, real school financial-aid PII, or application production certification.
- This does not resolve the earlier missing subscription-wide spending and budget visibility; paid tiers and broad production release remain blocked.

The historical proposal relied on a workflow and branch protections outside this
repository; neither is evidence of current Jireh safeguards.

Official reference: https://learn.microsoft.com/en-us/azure/static-web-apps/quotas and https://learn.microsoft.com/en-us/azure/static-web-apps/static-web-apps-cli-deploy

## Historical October 18 staging authorization — superseded

The prior CROWN staging authorization does not apply to this separate Jireh
repository. Do not provision, deploy, change DNS, or use real data without
separate approval and current evidence.
