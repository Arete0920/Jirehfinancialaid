# Jireh release acceptance procedures

Use the [release ledger](PRODUCTION_READINESS.md) as the authority for observed gate status. The [owner cutline](https://github.com/Arete0920/Jirehfinancialaid/issues/48#issuecomment-7241604472) closes offline workstation installation and owner acceptance of the guided presentation. November 30 is the completion target and December 1 is the release-readiness target. Enter an exact SHA, environment, timestamp, reviewer, evidence reference and decision for each new acceptance result.

## Provider-independent pending payment

The owner approved the #45 and #50 pending-payment lifecycle and migration and retained the $55 fee for each school's annual household application. The application remains DRAFT. The synthetic service stores the fee obligation and the exact saved handoff, which identifies the school, household, academic year, reviewing actor and questionnaire revision. It requires the current fictional disclosure. It stores no financial answers or payment credentials.

A current authorized retry returns the same record. The service revalidates the saved handoff during preparation and refresh. If it detects a changed review, it records the invalidation even when it rejects the attempted retry. An evidence-read failure blocks the retry and preserves the attempt so a later authorized retry can succeed. Withdrawal targets one attempt and can be retried without affecting a later attempt. Invalidated records remain as history and cannot be reopened. The existing application lock and database uniqueness enforce one current attempt per application.

The service is available only inside the existing fictional acceptance scope. Use the live policy baseline below for design and acceptance. Live privacy review, lifecycle implementation and provider acceptance remain open. Final submission requires verified settlement against the approved obligation and a separately authorized transition with an atomic audit record. Provider evidence and settlement semantics must be confirmed before enabling that transition.

For hosted acceptance, test exact and conflicting concurrent retries, stale or withdrawn review, revoked access and cross-school scope. Once the provider contract is approved, exercise duplicate or replayed payment events, wrong amount or currency, mismatched obligations, late reversals and rollback when state and audit cannot both be recorded.

## Live consent, amendments, and fee exceptions

The owner delegated these product decisions for #45 and #50 on November 28. Use this baseline for contract design and acceptance. Publish the live disclosure only after privacy review confirms the wording against the approved privacy notice, collection and retention policies, and school agreements. Schema and live release approvals remain separate.

### Consent and attestation

Use `jireh-financial-aid-consent-v1` for use consent. Present this clause before accepting live financial answers or supporting documents. Record the authorized actor, purpose, school, household, application, academic year, and server time.

> I confirm that I am authorized to provide the information and documents for this household’s application. I authorize the school named on this application and Jireh, acting on the school’s behalf, to use the information and documents to review this financial aid application for the academic year shown and administer any resulting aid, as described in the linked privacy notice. I understand that the $55 application fee covers all children in this household’s application to this school for this academic year. Award decisions follow the school’s financial aid review.

Use `jireh-accuracy-attestation-v1` for accuracy attestation at the completed application review.

> I have reviewed this application and attest that the information is accurate to the best of my knowledge.

Display the school, academic year, and approved privacy notice with the use consent. At the completed review, use separate, unchecked affirmative controls for reaffirming use consent and attesting accuracy. Bind both responses to the exact saved review. Store the version and digest of each clause and record which clause the actor affirmed at each step. Any change to a clause requires a new version and an affirmative response. Keep approval records free of financial answers and payment credentials. Future prior-year reuse requires separate permission. A withdrawal blocks further reliance on the withdrawn consent. Retain evidence according to the applicable approved schedule or hold.

### Edits, withdrawal, and final submission

- Keep the draft editable before final submission, including after verified payment. Applicant edits to answers, selected children, documents, or the disclosure invalidate the previous review and require fresh review and attestation. Keep school, household, and academic-year scope fixed after payment. An attempt loses eligibility when its review is stale, when withdrawn, or when the approved submission window closes.
- A settled charge stays bound to its original fee obligation. If payment settles against an invalid attempt or the household edits the draft after payment, hold final submission and collection retries for review. An authorized reconciliation decision can apply a verified charge only to its originating obligation, after fresh consent and review and while the intake window is open and all applicable gates pass. Keep the original attempt and settlement history. If the charge cannot be applied, route it to refund review.
- Require a distinct authorized submission action and verified settlement for the current approved obligation. Preserve the submitted snapshot. After submission, the family may request a correction or withdrawal. Require a scoped, authorized review and an auditable versioned amendment before a correction takes effect. Preserve the original submission and any authorized retention or hold.

### Fee exceptions

- Disclose the USD $55 fee at the submission step. An explicit authorized payment action after affirmative review initiates collection for the annual school and household application. Final submission remains a separate action after verified settlement. A retry or additional child creates no second obligation. Route verified duplicate or wrong-amount charges to a restricted exception review before any refund. If a verified payment cannot be applied to a valid application after review, route it to the same refund review.
- Require a named finance approver, the verified original transaction, a reason, and a durable audit record for refunds. Return funds through the original transaction where the verified provider contract permits. A later withdrawal or aid denial after successful submission triggers no automatic refund. Apply statutory and school-agreement obligations after review.
- Keep waivers disabled pending a separately approved eligibility and authorization policy. A waived fee, receipt screenshot, or browser redirect cannot establish verified settlement.
- Isolate chargebacks and late or unmatched settlements in exception review. A reversal blocks any pending final submission that relies on that charge. If a case was already submitted, record the dispute against its payment history and retain the submitted snapshot and any award decision for authorized review. An event retry produces no additional collection, refund, or lifecycle transition.

Provider acceptance must test each exception using the authenticated CompuWerx contract and its test environment. Customer-facing disclosures, retention schedules, role grants, and implementation of a live transition remain release gates.

## Monday Azure inventory and acceptance

Use the authorized Jireh Azure identity and explicit subscription selection. Run only the read operations below during inventory. Record the subscription and resource group scope privately and publish sanitized evidence in #48. A denied entitlement or unavailable cost dataset is an unresolved gate.

```sh
az account show --subscription "$JIREH_SUBSCRIPTION" --query '{name:name,state:state}'
az group list --subscription "$JIREH_SUBSCRIPTION" --query '[].{name:name,location:location}'
az resource list --subscription "$JIREH_SUBSCRIPTION" --resource-group "$JIREH_RESOURCE_GROUP" \
  --query '[].{name:name,type:type,location:location,sku:sku.name}'
```

Review resource roles and entitlement for inventory, deployment, operations, diagnostics and billing separately. Check actual and forecast spend in Cost Management for the agreed Jireh scope. Estimate compute, PostgreSQL, storage and backup, networking and egress, DNS, monitoring and log retention, and secret management. Include limits, region and recurring minimums. Treat $50/month as a ceiling. Prefer free capacity only where mandatory controls fit. Obtain approval of topology and cost before creating resources or changing permissions.

| Sequence | Synthetic acceptance and evidence |
| --- | --- |
| D1–D3 | Approve topology, network exposure and budget. Use the exact approved artifact. Apply private/TLS database connectivity with verified server identity, scoped runtime role, separately authorized migration role, approved secret storage and exact allowed hosts. Confirm closed routes, readiness failure on database loss, backup and restore and rollback. |
| T1–T2, S1 | Rehearse two schools, distinct households and revoked access. Verify invite and recovery restrictions, separate director and operator authority, CSRF, denial paths and audit continuity. Test real role grants under the intended runtime login with fictional fixtures. |
| S2 | Check authorized object access, storage and scanner failure behavior, encryption and key separation, retention, backup and restore. Preserve sensitive diagnostics and document contents outside shared evidence. |
| M1–M2, I1 | Name primary and backup responders, obtain approved alert destinations and thresholds, use synthetic failures to verify alert receipt and recovery behavior, and exercise the existing incident procedure. Record observed RPO/RTO against approved objectives. |
| A1 | Link observed results for the same candidate and environment. Obtain explicit owner and operational approval for the authorized release scope. Keep real intake, activation and paid submission closed until their gates pass. |

### Restricted runtime evidence

After topology and deployment authorization, run the closed-runtime preflight from the release SHA using the approved hostname and the same runtime configuration and database login. Inject the database secret through the approved runtime mechanism. Record the served SHA from deployment metadata separately.

```sh
PYTHONPATH=src python scripts/verify_restricted_runtime.py "${JIREH_HTTPS_ORIGIN:?Set the approved HTTPS origin}"
PYTHONPATH=src python scripts/verify_restricted_runtime.py --outage "${JIREH_HTTPS_ORIGIN:?Set the approved HTTPS origin}"
```

Run the second command only during an independently authorized outage exercise on the isolated environment. It observes liveness 200 and sanitized readiness 503 without initiating an outage. Repeat the normal command after database connectivity returns and record alert delivery separately.

The normal command verifies server trust for its HTTPS and PostgreSQL connections. The CLI origin must exactly select a host from the trusted runtime allowlist on standard HTTPS port 443 (with or without a trailing slash or explicit `:443`). Arbitrary ports, paths, user information, queries, and fragments are rejected before opening any connection. Its PostgreSQL connection uses the configured runtime login with `sslmode=verify-full`. It checks the configured login’s identity, reachable PostgreSQL predefined roles and direct privileges on the database, the `public` schema, and application relations in that schema. It reads only PostgreSQL catalogs. Review the deployed route configuration, `DEBUG=False`, and indirect access through database functions separately. Both commands emit fixed evidence summaries without response bodies, connection strings, or credentials.

Treat successful probes as process and database-connectivity evidence. The current runtime exposes only those two routes. The financial and operator test profiles require disposable environments. Hosted customer and operator journeys require a separately approved restricted runtime and target-environment evidence for authorization, data protection and audit continuity.

Run the independent Arete operator journey from verified identity through inactive school preparation, retry and registry readback. Verify denial for an unauthorized role, revocation, failed recovery, and attempts to activate a school prematurely. Define support routing and two-person approval before any real onboarding. Use the existing [operations incident procedure](PRODUCTION_READINESS.md#operational-incident-response-procedure-draft-not-certified) and record alert delivery and named responders only after validation.

## CompuWerx acceptance preparation

Obtain independent acceptance of the prepayment release and separate owner authorization before contacting the provider or beginning provider-specific activity. Then obtain the real provider contract, supported test environment, access roles, authentication and signing rules, test credentials, authoritative transaction states, idempotency and retry semantics, reconciliation export and outage support. Validate backend-to-provider and inbound event trust from the actual contract before writing an adapter. Keep browser redirects and client assertions outside the settlement trust boundary.

Exercise exact $55 obligation reconciliation, duplicate and late events, invalid signatures, failed payment, mismatched amount/currency/scope, provider outage and reconciliation conflicts with test data. Evaluate refunds, waivers, chargebacks and cross-school treatment under the approved policies. Verify one durable audit and state transition per approved obligation, retention of sanitized proof, and operator exception handling. Paid operation requires same-environment acceptance and separate release authorization.

## Outstanding issue reconciliation

| Existing issues | Reuse and remaining decision |
| --- | --- |
| [#43](https://github.com/Arete0920/Jirehfinancialaid/issues/43), [#44](https://github.com/Arete0920/Jirehfinancialaid/issues/44) | Reuse the 31-field development catalog, revision-bound encrypted draft and scoped synthetic document lifecycle. Obtain approved field applicability, collection/retention, access, verification and hosted storage/scanning decisions. |
| [#45](https://github.com/Arete0920/Jirehfinancialaid/issues/45), [#50](https://github.com/Arete0920/Jirehfinancialaid/issues/50) | Owner approved the fictional lifecycle, migration and existing $55 fee scope. Apply the delegated live policy baseline above. Complete privacy review, lifecycle implementation and provider acceptance separately. |
| [#46](https://github.com/Arete0920/Jirehfinancialaid/issues/46), [#47](https://github.com/Arete0920/Jirehfinancialaid/issues/47) | Reuse current fictional need estimate, review journal and nonbinding decisions. Approve methodology, school-specific categories, award role/authority and adjustment rules before commercial awards. |
| [#49](https://github.com/Arete0920/Jirehfinancialaid/issues/49), [#109](https://github.com/Arete0920/Jirehfinancialaid/issues/109) | Reuse synthetic invitations, registry, preparation and inactive provisioning. Verify institutional identity, support/credential recovery, two-person grants and authorized target-environment operations. |
| [#48](https://github.com/Arete0920/Jirehfinancialaid/issues/48), [#51](https://github.com/Arete0920/Jirehfinancialaid/issues/51) | Track target release gates in #48. Keep optional partnerships and multi-school features deferred under #51. |
