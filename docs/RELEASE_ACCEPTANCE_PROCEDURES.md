# Jireh release acceptance procedures

Use the [release ledger](PRODUCTION_READINESS.md) as the authority for observed gate status. The [owner cutline](https://github.com/Arete0920/Jirehfinancialaid/issues/48#issuecomment-7241604472) closes offline workstation installation and owner acceptance of the guided presentation. November 30 is the completion target and December 1 is the release-readiness target. Enter an exact SHA, environment, timestamp, reviewer, evidence reference and decision for each new acceptance result.

## Provider-independent pending payment

The owner approved the #45 and #50 pending-payment lifecycle and migration and retained the $55 fee for each school's annual household application. The application remains DRAFT. The synthetic service stores the fee obligation and the exact saved handoff, which identifies the school, household, academic year, reviewing actor and questionnaire revision. It requires the current fictional disclosure. It stores no financial answers or payment credentials.

A current authorized retry returns the same record. The service revalidates the saved handoff before returning a current attempt and marks the attempt invalid when the review changes. Withdrawal targets one attempt and can be retried without affecting a later attempt. Invalidated records remain as history and cannot be reopened. The existing application lock and database uniqueness enforce one current attempt per application.

The service is available only inside the existing fictional acceptance scope. Live consent wording, expiration and amendment policy, refunds, waivers, chargebacks, and treatment of settlement after invalidation remain open. Final submission requires verified settlement against the approved obligation and a separately authorized transition with an atomic audit record. Provider evidence and settlement semantics must be confirmed before enabling that transition.

For hosted acceptance, test exact and conflicting concurrent retries, stale or withdrawn review, revoked access and cross-school scope. Once the provider contract is approved, exercise duplicate or replayed payment events, wrong amount or currency, mismatched obligations, late reversals and rollback when state and audit cannot both be recorded.

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
| [#45](https://github.com/Arete0920/Jirehfinancialaid/issues/45), [#50](https://github.com/Arete0920/Jirehfinancialaid/issues/50) | Owner approved the fictional lifecycle, migration and existing $55 fee scope. Obtain live consent and commercial exception decisions, and complete provider acceptance separately. |
| [#46](https://github.com/Arete0920/Jirehfinancialaid/issues/46), [#47](https://github.com/Arete0920/Jirehfinancialaid/issues/47) | Reuse current fictional need estimate, review journal and nonbinding decisions. Approve methodology, school-specific categories, award role/authority and adjustment rules before commercial awards. |
| [#49](https://github.com/Arete0920/Jirehfinancialaid/issues/49), [#109](https://github.com/Arete0920/Jirehfinancialaid/issues/109) | Reuse synthetic invitations, registry, preparation and inactive provisioning. Verify institutional identity, support/credential recovery, two-person grants and authorized target-environment operations. |
| [#48](https://github.com/Arete0920/Jirehfinancialaid/issues/48), [#51](https://github.com/Arete0920/Jirehfinancialaid/issues/51) | Track target release gates in #48. Keep optional partnerships and multi-school features deferred under #51. |
