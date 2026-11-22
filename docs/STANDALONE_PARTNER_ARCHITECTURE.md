# Standalone Jireh — product architecture and partner guardrails

**Status:** Architecture constraints and deferred design decisions; **not** an
implementation authorization or production approval.

**Evidence baseline:** `Arete0920/Jirehfinancialaid` `main`
`bd4a46da837ea43097ad9128de279c0a3bb7dc60`, verified
2026-11-22. Authoritative existing contracts are `README.md`,
`src/jireh/schools/models.py`, `src/jireh/financial_aid/models.py`,
`src/jireh/financial_aid/fees.py`, and the standalone runtime settings.
If any of those change, reconcile this document to the accepted `main` SHA.

## Product boundaries already established

1. **Jireh is an independent product.** It must function without CROWN or
   another SIS. Any future SIS or tuition connection is optional and must not
   become a database, authentication, hosting, or business-logic dependency.
2. **A school is an authorization boundary.** A `Household`, `Student`,
   `AcademicYear`, and `AidApplication` are currently school-bound.
   `AidApplication` has a database-enforced unique constraint for
   (school, academic year, household). One school's grant, staff role, or
   financial-aid record does not authorize access to another school's data.
   A child linked to separate households does not join their financial
   records or entitle either parent to the other household's application.
3. **The primary journey is one family applying to one school.**
   An application may include multiple children linked to that specific
   household. Each school independently controls its financial-aid process
   and eventual awards; current code only supports DRAFT records and
   test-only routes, not a complete financial-aid workflow.
4. **The established fee contract is $55 per household, family-paid,**
   regardless of child count. Payment timing, refunds, payment processor,
   waivers, and treatment of an additional school are not approved or
   implemented. Do not infer a multi-school all-inclusive fee.
5. **Jireh SGO is excluded** from this standalone product. The existing
   need, mission, marketing/enrollment, merit and hardship aid-bucket
   identifiers are not a completed award-analysis engine.
6. **Commercial launch remains NO-GO.** Hosting, production routes,
   live credential recovery, real family data, payment collection, and
   partner access are not enabled by this document.

## Terminology: one platform is not one school application record

- **Platform:** one independently operated Jireh codebase/product designed
  to serve many independently isolated school tenants; no per-school
  deployment or per-school source fork should be required.
- **Family account:** a possible future sign-in identity. An account
  authenticated to Jireh is **not** automatically authorized to view a
  household, school, sibling household, or another school's application.
- **Household financial information:** sensitive information that must
  remain private and access-controlled, even when future reuse is allowed.
- **School submission/application:** the school-bound request, consent,
  review, audit trail, and aid decision. A family choosing two schools
  must not cause their schools to share application privileges or awards.

## Future capability design constraints

### Optional SIS and distribution partners — proposed, not implemented

- Use independently versioned, authenticated and authorized integration
  contracts. A partner must not access the shared database directly or
  gain blanket rights to every school or family in its distribution network.
- Resolve school identity from server-verified configuration and explicit
  school-scoped authorizations, **never solely from a hostname, HTTP
  header, SIS identifier, email domain, or branding parameter**.
- Map external SIS identifiers only within a verified school-and-partner
  scope. Handle revocation, replay, duplicates, out-of-order events,
  credential rotation, and audit evidence before any live integration.
- Integration failures must not disable local Jireh identity or permit
  bypass of tenant authorization. External SSO, APIs, webhooks and
  synchronizations each require their own reviewed threat model and tests.
- Partner support should see only authorized integration/operational
  diagnostics by default, not family financial data or school award records.

### Configurable school identity — proposed, not implemented

- A participating school may eventually configure approved logo,
  display name, colors, instructions, deadlines and school-specific
  supplemental questions from an allowlisted, validated schema.
- Presentational branding must **never** set the tenant security context,
  turn on payment or recovery gates, alter consent, or grant admin roles.
- Separate school settings from commercial white-label or reseller
  rights. The latter need explicit owner-approved contracts and controls.
- Maintain safe platform defaults and ensure school content and uploaded
  branding cannot execute scripts or expose credentials.

### Exceptional multi-school family use — proposed, not implemented

- **Do not replace or loosen the existing school-bound household and
  aid-application constraints** just to support cross-school convenience.
- Retain independent school submissions, each with their own school
  authorization, deadlines, record state, school-specific responses,
  documents, audit and award decisions.
- A future reusable family-controlled profile **may** supply information
  to a second school only after explicit, recorded authorization covering
  the recipient school, data categories, purpose and applicable time
  period. No silent cross-school joins, shared mutable financial records
  or automatic grant inheritance.
- Design consent withdrawal, corrections, legal retention, and prior
  submissions as explicit policy decisions before implementation. Never
  promise retroactive erasure from a previously authorized submission.
- Reuse is a convenience feature, **not** permission for one school or
  partner to inspect another school's application. Default UX remains
  one household, one school, one annual application.

### Operational and support boundaries

- Schools manage their own permitted staff, household access, local
  application rules, review and award decisions; Arete operates and
  supports the underlying Jireh platform.
- Future roles must distinguish platform operator, school aid staff,
  SIS integration partner, and family. No implicit superuser or support
  bypass. Privileged actions require approval, least privilege, expiry,
  logging and independent identity checks where appropriate.
- Support workflows must not expose tax documents, raw financial answers,
  authenticator material or another tenant's data in tickets, logs or
  integration diagnostics.
- Mobile and browser clients must use the same authorized Jireh backend
  semantics instead of creating independent aid rules.

## Delivery sequence (guardrails, not an authorization to build)

1. **P0: preserve the security and operational acceptance work.** Resolve
   existing production NO-GO gates, including test-only route isolation,
   tenant integrity, monitoring, incident response, and credential safety.
2. **P1: complete the standard one-school application.** Define and test
   financial collection, consent, safe documents, submission lifecycle,
   analysis, school review, awards, school support and fee decisions.
3. **P2: add bounded configuration and optional partner adapters.**
   Require school-scoped negative tests, data contracts, branding safety,
   integration audit events, and authorization before exposing live APIs.
4. **P3: add opt-in multi-school reuse only when justified by demand.**
   Do not force a globally shared household model into P1 or P2.

Before any code change implementing these proposals, require targeted tests
for two schools, distinct and shared-child households, revoked access,
header/ID spoofing, missing/withdrawn consent, partner privilege boundaries,
school-specific data visibility, and audit continuity. For data-model
changes, separately verify migrations, rollback/restore, and PostgreSQL
integrity. Preserve the existing CI and protected-branch requirements.

## Decisions still required — do not guess

- Whether **$55** covers only the original school or multiple participating
  schools within an annual cycle; waiver, refund and processor policy.
- Whether/when an identity may reuse selected financial data across
  schools; consent form, data lifecycle, retention and school notification.
- SIS partner API/SSO capabilities, versioning, distribution rights,
  branding limits, data processor responsibilities and contractual terms.
- Configurable school content validation, administrative permission matrix
  and actual support service-level agreements.
- Hosting topology, cryptographic key management, audit retention,
  monitoring ownership and incident-response contacts.

**Change-control rule:** This document is deliberately additive and
non-executable. It neither modifies current code nor certifies these future
features. Keep the product production **NO-GO** until separately evidenced
security, operational and owner/integration-manager acceptance.
