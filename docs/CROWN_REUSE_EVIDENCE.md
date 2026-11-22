# CROWN financial-aid reuse register — first executable checkpoint

**Status:** Historical reference preserved; **NO standalone award engine approved.**
**Source repository:** [Arete0920/Crown-CSMS](https://github.com/Arete0920/Crown-CSMS), immutable SHA `46b56609fe18360299b08eabaa8bccdffb356a0e`.
**Destination baseline:** [Arete0920/Jirehfinancialaid](https://github.com/Arete0920/Jirehfinancialaid), protected main `5d9162a3bfa3917512a12fee8b74f6c050ce0a56`.

## Executable historical parity evidence

- Source: `backend/aid/services/award_engine.py` → `tests/legacy_crown/award_engine.py`.
- Source: `backend/aid/tests/test_aid_engine.py` → `tests/test_crown_award_parity.py`.
- **Only test import changes:** Django `TestCase` becomes standard-library `unittest.TestCase`; the imported engine location points to the test-only reference package. This avoids requiring application models or running a database for parity checks.
- The historical engine's calculation functions and old test assertions are otherwise retained. No Jireh runtime module imports this reference. Run with the existing Python contract job: `PYTHONPATH=src python -m unittest discover -s tests -v`.
- Verify the exact candidate GitHub SHA and full CI results before asserting successful parity. The historical test suite does **not** establish the correctness, appropriateness, or safety of the methodology.

## Reuse decision matrix (initial read-only triage)

| CROWN asset | Initial finding | Standalone disposition |
| --- | --- | --- |
| `backend/aid/services/award_engine.py` | Pure calculation; deterministic outputs for given inputs; reads no CROWN ORM or ledger | **Preserved as test-only reference.** Candidate for a separately reviewed, policy-driven standalone implementation |
| `backend/aid/tests/test_aid_engine.py` | Existing boundary, numeric and recommendation tests | **Portable tests captured** with import changes only |
| `backend/aid/services/profile_service.py` | Current-year financial line items, provenance, validation and prior-year consent; direct `aid.models` and Django dependencies | **Adapt concepts**, not wholesale code |
| `backend/aid/models.py` | School/year scoped applications, review, award budget, profiles, household member and questions | **Map schema and policies**, preserving independently verified standalone household grants and UUID tenants |
| `backend/financial_aid/need_index.py` | Separate weighted need-index approach, with CROWN `TuitionPlan` dependency and fixed fallback values | **Do not merge formulas** until owner selects a method |
| `backend/financial_aid/workflows.py` | Application processing depends on `signals`, `core`, Solomon, Crown Compass and other CROWN systems | **Do not port directly** |
| `backend/aid/services/ledger_bridge.py` | Uses CROWN `core`, `households`, `ledger` and student-account posting | **Do not port directly**; reuse tested idempotency / reversal requirements for future optional adapters |
| `backend/aid/tests/test_aid_award_invariants.py` | Ledger sign, double posting, reversal, audit tests | **Retain as future acceptance requirements**; not standalone payment approval |
| `backend/aid/services/award_engine.py` mission factors | Policy weights and adjustments tied to faith/church participation; potential fairness and legal issues | **Do not activate** without product-owner policy and legal/privacy review |

## Source-level concerns identified before porting

1. The legacy need computation applies fixed rates of 20% to income above the floor and 5% to net assets. These assumptions have not been commercially or legally accepted for standalone Jireh.
2. The legacy engine uses binary floating-point multipliers and `int(...)` truncation for money; a production calculator should adopt explicit integer/decimal rounding and range contracts.
3. The legacy mission modifier can lower the recommended award below the minimum configured percentage, according to its historical tests; whether this behavior is acceptable is an owner decision.
4. The `backend/financial_aid/need_index.py` pathway instead assigns special weights and defaults to income, dependents, hardship and aid history. **Do not silently combine** these two systems.
5. Financial aid need and school-approved awards must remain distinct; no recommendation may post to accounts, authorize payment, or create a final decision without school-scoped review.
6. Existing Jireh `AidApplication` has only DRAFT data, no financial input schema, policy model, assessment service, or production customer APIs; importing historical tests must not change that.

## Next implementation gate

Product owner must approve field taxonomy, need methodology/constraints, consent and data-handling rules. Only then prepare a separate bounded production implementation for issues [#43](https://github.com/Arete0920/Jirehfinancialaid/issues/43) and [#46](https://github.com/Arete0920/Jirehfinancialaid/issues/46), with CROWN parity tests and **new independent negative tests**. Preserve CROWN as the authoritative legacy source for any further reconciliation. Do not enable production, migrations, real data or payments through this register.
