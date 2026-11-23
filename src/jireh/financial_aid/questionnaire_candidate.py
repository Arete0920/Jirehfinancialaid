"""Strict, non-persistent candidate v1 financial-row validation.

The owner approved 31 field paths for development, NOT money bounds, periods,
data collection, school-specific questions, consent text or production access.
The caller must supply independently reviewed money bounds, reporting year,
category subset and authorized household member identifiers. These parameters
are not authorization: a future service must derive them from trusted school
policy and active household grants, never from client JSON.

No Django imports, I/O, storage, routes, CROWN coupling, score or payment.
"""
from dataclasses import dataclass
from uuid import UUID

from .questionnaire_validation import (
    QuestionnaireValidationError,
    ValidatedBalance,
    ValidatedFlow,
    validate_balance,
    validate_calendar_year_flow,
)


# Frozen paths/types from the owner-approved November 22 field-list checkpoint.
# This is a DEVELOPMENT contract; choices, requiredness and privacy rules are
# NOT certified. Catalog changes must be explicitly reviewed, not guessed.
V1_FIELD_TYPES = {
    "household.members[].member_id": "identifier",
    "household.members[].role": "enum",
    "household.members[].relationship": "enum",
    "household.members[].resides_in_household": "boolean",
    "household.members[].financial_contributor": "boolean",
    "household.members[].student_link_id": "identifier",
    "income.items[].category": "enum",
    "income.items[].amount": "money_flow",
    "income.items[].period_start": "date",
    "income.items[].period_end": "date",
    "income.items[].contributor_id": "identifier",
    "income.items[].source_type": "enum",
    "assets.items[].category": "enum",
    "assets.items[].balance": "money_balance",
    "assets.items[].as_of_date": "date",
    "assets.items[].owner_member_id": "identifier",
    "liabilities.items[].category": "enum",
    "liabilities.items[].balance": "money_balance",
    "liabilities.items[].as_of_date": "date",
    "liabilities.items[].responsible_member_id": "identifier",
    "expenses.items[].category": "enum",
    "expenses.items[].amount": "money_flow",
    "expenses.items[].period_start": "date",
    "expenses.items[].period_end": "date",
    "school_questions[].definition_id": "identifier",
    "school_questions[].definition_version": "short_text",
    "school_questions[].answer": "question_answer",
    "consent.current_year_accuracy": "consent_decision",
    "consent.prior_year_reuse": "consent_decision",
    "consent.attestation_actor_id": "identifier",
    "consent.attestation_timestamp": "timestamp",
}
V1_SECTIONS = frozenset(
    ("household", "income", "assets", "liabilities", "expenses",
     "school_questions", "consent")
)
FINANCIAL_FIELDS = {
    "income": frozenset(
        ("category", "amount", "period_start", "period_end", "contributor_id")
    ),
    "expenses": frozenset(
        ("category", "amount", "period_start", "period_end")
    ),
    "assets": frozenset(
        ("category", "balance", "as_of_date", "owner_member_id")
    ),
    "liabilities": frozenset(
        ("category", "balance", "as_of_date", "responsible_member_id")
    ),
}
MEMBER_FIELD = {
    "income": "contributor_id",
    "assets": "owner_member_id",
    "liabilities": "responsible_member_id",
}
_NO_COLLECTION_REQUIREMENTS = frozenset(
    ("no_production_routes", "no_data_storage", "no_financial_scoring",
     "no_implicit_carry_forward", "no_inferred_household_access",
     "explicit_consent_for_reuse", "versioned_question_definitions",
     "audit_metadata_only")
)


@dataclass(frozen=True, slots=True, repr=False)
class ValidatedCandidateFinancialRecord:
    """Structural result only; not an authorized or verified financial record."""

    section: str
    category: str
    value: ValidatedFlow | ValidatedBalance
    member_id: UUID | None


def _invalid(code):
    raise QuestionnaireValidationError(code)


def validate_v1_field_catalog(catalog: object) -> dict:
    """Fail closed if the documented 31-field development contract drifts.

    The returned data is for local policy/shape checks only. It MUST NOT be
    accepted from a network request or used as a live field-publishing source.
    """
    if type(catalog) is not dict:
        _invalid("candidate_catalog_invalid")
    approval = catalog.get("field_list_approval")
    requirements = catalog.get("requirements")
    if (
        catalog.get("schema_status")
        != "FIELD_LIST_APPROVED_DESIGN_ONLY_NOT_COLLECTION"
        or type(approval) is not dict
        or approval.get("status") != "OWNER_APPROVED_FOR_DEVELOPMENT"
        or approval.get("approved_field_count") != 31
        or type(requirements) is not dict
        or any(requirements.get(name) is not True
               for name in _NO_COLLECTION_REQUIREMENTS)
    ):
        _invalid("candidate_catalog_not_approved_for_design")

    sections = catalog.get("sections")
    if type(sections) is not list or len(sections) != len(V1_SECTIONS):
        _invalid("candidate_catalog_sections_invalid")
    found_sections = set()
    fields = {}
    for section in sections:
        if type(section) is not dict:
            _invalid("candidate_catalog_sections_invalid")
        section_id = section.get("id")
        if (
            type(section_id) is not str
            or section_id not in V1_SECTIONS
            or section_id in found_sections
            or section.get("lifecycle") != "approved_for_development"
            or type(section.get("fields")) is not list
        ):
            _invalid("candidate_catalog_sections_invalid")
        found_sections.add(section_id)
        for field in section["fields"]:
            if type(field) is not dict:
                _invalid("candidate_catalog_fields_invalid")
            field_id = field.get("id")
            field_type = field.get("type")
            if (
                type(field_id) is not str
                or field_id in fields
                or V1_FIELD_TYPES.get(field_id) != field_type
                or not (
                    field_id.startswith(section_id + ".")
                    or field_id.startswith(section_id + "[].")
                )
            ):
                _invalid("candidate_catalog_fields_invalid")
            if field_type == "enum":
                choices = field.get("choices")
                if (
                    type(choices) is not list
                    or not choices
                    or any(type(choice) is not str or not choice
                           or choice.strip() != choice for choice in choices)
                    or len(set(choices)) != len(choices)
                ):
                    _invalid("candidate_catalog_choices_invalid")
            fields[field_id] = field
    if set(fields) != set(V1_FIELD_TYPES):
        _invalid("candidate_catalog_fields_invalid")
    return fields


def _approved_category(value: object, candidate_choices: object, approved: object):
    """Require an independent, exact candidate-subset allowlist from policy."""
    if (
        type(approved) is not tuple
        or not approved
        or any(type(x) is not str or not x for x in approved)
        or len(set(approved)) != len(approved)
        or type(candidate_choices) is not list
        or not set(approved).issubset(set(candidate_choices))
    ):
        _invalid("candidate_category_policy_missing")
    if type(value) is not str or value not in approved:
        _invalid("candidate_category_not_allowed")
    return value


def _scoped_member(value: object, allowed_members: object) -> UUID:
    if (
        type(allowed_members) is not tuple
        or not allowed_members
        or any(type(item) is not str for item in allowed_members)
    ):
        _invalid("candidate_member_scope_missing")
    if type(value) is not str:
        _invalid("candidate_member_invalid")
    try:
        member = UUID(value)
    except (TypeError, AttributeError, ValueError):
        _invalid("candidate_member_invalid")
    if str(member) != value:
        _invalid("candidate_member_invalid")
    if value not in allowed_members:
        _invalid("candidate_member_scope_denied")
    return member


def validate_v1_financial_candidate(
    *,
    catalog: object,
    section: object,
    record: object,
    approved_categories: object,
    min_cents: object,
    max_cents: object,
    reporting_year: object = None,
    authorized_member_ids: object = None,
) -> ValidatedCandidateFinancialRecord:
    """Validate a complete fictional row, not collect or calculate finances.

    No implicit income tax year, expense annualization, categorical allowance,
    negative-amount rule, household access or money bounds are inferred.
    The caller must independently authorize category and member scope.
    """
    fields = validate_v1_field_catalog(catalog)
    if type(section) is not str or section not in FINANCIAL_FIELDS:
        _invalid("candidate_section_unsupported")
    allowed_keys = FINANCIAL_FIELDS[section]
    if type(record) is not dict or set(record) != allowed_keys:
        _invalid("candidate_record_shape_invalid")

    category_field_id = (
        f"{section}.items[].category"
    )
    category = _approved_category(
        record["category"], fields[category_field_id]["choices"],
        approved_categories,
    )
    if section in ("income", "expenses"):
        financial = validate_calendar_year_flow(
            reporting_year=reporting_year,
            amount_cents=record["amount"],
            period_start=record["period_start"],
            period_end=record["period_end"],
            min_cents=min_cents,
            max_cents=max_cents,
        )
    else:
        financial = validate_balance(
            balance_cents=record["balance"],
            as_of_date=record["as_of_date"],
            min_cents=min_cents,
            max_cents=max_cents,
        )

    member_id = (
        _scoped_member(record[MEMBER_FIELD[section]], authorized_member_ids)
        if section in MEMBER_FIELD else None
    )
    return ValidatedCandidateFinancialRecord(
        section=section, category=category, value=financial, member_id=member_id
    )
