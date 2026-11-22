# Jireh questionnaire — side-effect-free validation primitives

**Status: ENGINEERING PRIMITIVES ONLY.** The seven questionnaire **sections** were
approved, but individual financial fields, applicable tax years, amount limits,
contributor rights, document requirements and actual consent language remain
unapproved. This module must not be connected to real-family data yet.

`src/jireh/financial_aid/questionnaire_validation.py` provides strictly
side-effect-free, policy-parameterized validation helpers:

- `validate_amount_cents(value, *, min_cents, max_cents)` requires an exact
  Python integer, rejects booleans and decimal/string coercion, and requires
  explicit integer bounds supplied by an independently approved caller policy.
  There is **no default nonnegative limit**: synthetic tests exercise both
  nonnegative and separately configured negative ranges. `None` and missing
  answers do not become zero.
- `validate_flow(..., period_start, period_end, min_cents, max_cents)` requires
  valid `YYYY-MM-DD` dates and a non-inverted interval. It does not annualize,
  normalize to a tax year, determine countable income or categorize expense.
- `validate_calendar_year_flow(..., reporting_year, ...)` requires a caller-
  selected integer calendar year and rejects flows with either endpoint outside
  it; it never selects the school aid-cycle reporting year or splits/annualizes.
- `validate_typed_question_answer(..., answer_type, enum_options)` supports
  strict boolean and exact-option enum *candidate* wire types only. Enum
  options must be an explicit nonempty tuple of distinct, nonblank strings;
  unsupported types, nested JSON, missing answers and coercion fail closed.
  The choices in synthetic tests are **not approved school questions**. This
  helper is not evidence that a question, version, school/year scope, publisher,
  requiredness, or collection method has been authorized; Q06 remains gated.
- `validate_balance(..., as_of_date, min_cents, max_cents)` requires an exact
  snapshot date, not a flow or implied annual amount. It does not determine
  whether an asset/liability qualifies for financial assessment.
- `validate_optional_consent(value)` returns exactly one of `None`, `False`,
  or `True`. A true boolean alone is **not** valid documented consent:
  durable scope, authenticated actor, purpose, disclosure, version, server
  timestamp, withdrawal, and audit remain unimplemented.

The immutable result dataclasses use `repr=False` to avoid accidental
financial-value disclosure in ordinary logs; this is not a guarantee against
explicit dumps or tracing. Validation failures return fixed non-sensitive
codes. Error responses must never log or echo submitted amounts or dates.

**Isolation:** The validation module contains no Django import, database
access, household lookup, CROWN import, HTTP route, financial storage,
scoring, ledger or payment. **Its functions do not authorize callers.**
Every future service must first enforce Jireh's explicit school/household/year
access and verify response ownership server-side.

**Test evidence:** `tests/test_questionnaire_validation.py` exercises
success, limits, incorrect input types, absence-vs-zero, date parsing,
inverted periods, snapshot semantics, immutable result classes, tri-state
consent, and sanitized error codes. These are deliberately synthetic
examples, not production field bounds or legally reviewed consent.

Run:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_questionnaire_validation.py' -v
```

**Next required decision:** Resolve field-level policy and privacy gates
[issue #43](https://github.com/Arete0920/Jirehfinancialaid/issues/43)
and the 10 questions in
[docs/questionnaire_v1_field_catalog.json](questionnaire_v1_field_catalog.json)
before designing persistent financial answers or an authenticated intake API.
The consent and submission state machine remains [issue #45](https://github.com/Arete0920/Jirehfinancialaid/issues/45).
