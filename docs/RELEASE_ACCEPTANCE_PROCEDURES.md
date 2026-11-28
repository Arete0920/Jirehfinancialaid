# Jireh release acceptance procedures

Use the [release ledger](PRODUCTION_READINESS.md) as the authority for observed gate status. The [owner cutline](https://github.com/Arete0920/Jirehfinancialaid/issues/48#issuecomment-7241604472) closes offline workstation installation and owner acceptance of the guided presentation. November 30 is the completion target and December 1 is the release-readiness target. Enter an exact SHA, environment, timestamp, reviewer, evidence reference and decision for each new acceptance result.

## Pending payment design for owner review

The offline contract validates the identifiers and gate facts supplied by a trusted caller. The caller must resolve the current saved handoff and questionnaire revision together and establish the canonical fee quote, explicit accuracy attestation, approved disclosure, completeness and authorized household scope. The proposal gives no payment or submission authority.

Proposed durable design under #45 and #50, pending approval:

1. Keep the application in DRAFT and record pending payment separately. Bind each attempt to the existing application, exact school/household/year, actor, current saved review/handoff and disclosure version. Store no financial answers, payment credentials or browser-supplied settlement evidence in the attempt.
2. Derive the fee obligation server-side. Use the existing quote key for local identity. Establish one current attempt per application with a database uniqueness guarantee and transactional locking. An exact authorized replay returns the existing attempt. A changed review or withdrawal invalidates the old attempt without erasing history. A new attempt and its fee treatment require the approved rules.
3. Keep final submission closed until authenticated, durable payment reconciliation matches the approved obligation and all live submission gates still pass. Revalidate under the same transactional boundary. Record the transition and audit atomically. Preserve the current synthetic prepayment handoff as fictional evidence.
4. Review approval, schema, migration and rollback together. Approve legal consent text, amended and withdrawn application handling, whether the fee spans schools, expiration, refunds, waivers, chargebacks and treatment of a settlement received after an attempt becomes stale. Authoritative provider evidence, retry identifiers and settlement semantics remain open.

The implementation acceptance matrix includes concurrent exact retries, conflicting retries, stale or withdrawn review, revoked grant, another household/school/year, missing consent or approval, duplicate or replayed payment event, wrong amount or currency, mismatched obligation, late reversal, and write failure between state and audit. Every denied transition must leave the application and audit consistent. The offline proposal tests the inputs available today. Database and provider acceptance require separate execution.

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

Run the independent Arete operator journey from verified identity through inactive school preparation, retry and registry readback. Verify denial for an unauthorized role, revocation, failed recovery, and attempts to activate a school prematurely. Define support routing and two-person approval before any real onboarding. Use the existing [operations incident procedure](PRODUCTION_READINESS.md#operational-incident-response-procedure-draft-not-certified) and record alert delivery and named responders only after validation.

## CompuWerx acceptance preparation

Obtain independent acceptance of the prepayment release and separate owner authorization before contacting the provider or beginning provider-specific activity. Then obtain the real provider contract, supported test environment, access roles, authentication and signing rules, test credentials, authoritative transaction states, idempotency and retry semantics, reconciliation export and outage support. Validate backend-to-provider and inbound event trust from the actual contract before writing an adapter. Keep browser redirects and client assertions outside the settlement trust boundary.

Exercise exact $55 obligation reconciliation, duplicate and late events, invalid signatures, failed payment, mismatched amount/currency/scope, provider outage and reconciliation conflicts with test data. Evaluate refunds, waivers, chargebacks and cross-school treatment under the approved policies. Verify one durable audit and state transition per approved obligation, retention of sanitized proof, and operator exception handling. Paid operation requires same-environment acceptance and separate release authorization.

## Outstanding issue reconciliation

| Existing issues | Reuse and remaining decision |
| --- | --- |
| [#43](https://github.com/Arete0920/Jirehfinancialaid/issues/43), [#44](https://github.com/Arete0920/Jirehfinancialaid/issues/44) | Reuse the 31-field development catalog, revision-bound encrypted draft and scoped synthetic document lifecycle. Obtain approved field applicability, collection/retention, access, verification and hosted storage/scanning decisions. |
| [#45](https://github.com/Arete0920/Jirehfinancialaid/issues/45), [#50](https://github.com/Arete0920/Jirehfinancialaid/issues/50) | Reuse current handoff, fee and offline reconciliation. Obtain lifecycle, consent, schema and commercial policy approval before durable changes and provider certification. |
| [#46](https://github.com/Arete0920/Jirehfinancialaid/issues/46), [#47](https://github.com/Arete0920/Jirehfinancialaid/issues/47) | Reuse current fictional need estimate, review journal and nonbinding decisions. Approve methodology, school-specific categories, award role/authority and adjustment rules before commercial awards. |
| [#49](https://github.com/Arete0920/Jirehfinancialaid/issues/49), [#109](https://github.com/Arete0920/Jirehfinancialaid/issues/109) | Reuse synthetic invitations, registry, preparation and inactive provisioning. Verify institutional identity, support/credential recovery, two-person grants and authorized target-environment operations. |
| [#48](https://github.com/Arete0920/Jirehfinancialaid/issues/48), [#51](https://github.com/Arete0920/Jirehfinancialaid/issues/51) | Track target release gates in #48. Keep optional partnerships and multi-school features deferred under #51. |
