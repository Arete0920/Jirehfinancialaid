"""Synthetic-only contract tests for the 31 owner-approved v1 field paths.

No real financial answers, unauthorized category/limit assumptions, Django
storage, consent activation, scoring or production routes are exercised.
"""
import copy
import json
import unittest
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path
from uuid import uuid4

from jireh.financial_aid.questionnaire_candidate import (
    V1_FIELD_TYPES, V1_SECTIONS, validate_v1_field_catalog,
    validate_v1_financial_candidate,
)
from jireh.financial_aid.questionnaire_validation import (
    QuestionnaireValidationError,
    ValidatedBalance,
    ValidatedFlow,
)


CATALOG_FILE = (
    Path(__file__).resolve().parents[1]
    / "docs" / "questionnaire_v1_field_catalog.json"
)
SYNTHETIC_MEMBER = str(uuid4())


def catalog():
    return json.loads(CATALOG_FILE.read_text(encoding="utf-8"))


def income_record(**overrides):
    value = {
        "category": "EMPLOYMENT",
        "amount": 12500,
        "period_start": "2026-01-01",
        "period_end": "2026-12-31",
        "contributor_id": SYNTHETIC_MEMBER,
    }
    value.update(overrides)
    return value


def flow_options(section="income"):
    return {
        "catalog": catalog(),
        "section": section,
        "approved_categories": ("EMPLOYMENT",) if section == "income" else ("HOUSING",),
        "min_cents": 0,
        "max_cents": 100000,
        "reporting_year": 2026,
        "authorized_member_ids": (SYNTHETIC_MEMBER,),
    }


class CandidateCatalogContractTests(unittest.TestCase):
    def test_all_31_approved_paths_have_exact_expected_types_and_sections(self):
        result = validate_v1_field_catalog(catalog())
        self.assertEqual(len(result), 31)
        self.assertEqual({field["type"] for field in result.values()}, set(V1_FIELD_TYPES.values()))
        self.assertEqual(set(result), set(V1_FIELD_TYPES))
        self.assertEqual({section["id"] for section in catalog()["sections"]}, set(V1_SECTIONS))
        self.assertTrue(all(isinstance(field_id, str) and field_id for field_id in result))
        self.assertEqual(catalog()["schema_version"], "0.1.0")

    def test_catalog_drift_or_missing_approvals_fail_closed(self):
        mutations = [
            lambda c: c.update(schema_status="LIVE_COLLECTION_APPROVED"),
            lambda c: c["field_list_approval"].update(status="PENDING"),
            lambda c: c["field_list_approval"].update(approved_field_count=30),
            lambda c: c["requirements"].update(no_data_storage=False),
            lambda c: c["sections"].pop(),
            lambda c: c["sections"].append(copy.deepcopy(c["sections"][0])),
            lambda c: c["sections"][0]["fields"].pop(),
            lambda c: c["sections"][0]["fields"][0].update(type="unrestricted_json"),
            lambda c: c["sections"][1]["fields"][0].update(id="income.items[].unknown"),
            lambda c: c["sections"][1]["fields"][0].update(choices=[]),
            lambda c: c["sections"][1]["fields"][0].update(
                choices=["EMPLOYMENT", "OTHER_APPROVED"]
            ),
            lambda c: c["sections"][1]["fields"][0].update(
                choices=["EMPLOYMENT", "EMPLOYMENT"]
            ),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                record = catalog()
                mutate(record)
                with self.assertRaises(QuestionnaireValidationError) as caught:
                    validate_v1_field_catalog(record)
                self.assertTrue(str(caught.exception).startswith("candidate_catalog_"))

    def test_privacy_classification_and_requiredness_are_locked_for_all_31_fields(self):
        """Changing a reviewed privacy or requiredness label is catalog drift."""
        approved = catalog()
        for section_index, section in enumerate(approved["sections"]):
            for field_index, field in enumerate(section["fields"]):
                for key, changed in (
                    ("required", "UNREVIEWED_CHANGED"),
                    ("sensitivity", "public"),
                ):
                    with self.subTest(field=field["id"], metadata=key):
                        self.assertNotEqual(field[key], changed)
                        altered = copy.deepcopy(approved)
                        altered["sections"][section_index]["fields"][field_index][key] = changed
                        with self.assertRaisesRegex(
                            QuestionnaireValidationError,
                            "^candidate_catalog_governance_drift$",
                        ):
                            validate_v1_field_catalog(altered)

    def test_policy_decisions_must_remain_explicitly_unapproved_for_design_only(self):
        """No silent removal of unresolved policy gates or live label changes."""
        mutations = (
            lambda c: c.update(schema_version="1.0.0"),
            lambda c: c.pop("pending_owner_decisions"),
            lambda c: c["pending_owner_decisions"].pop(),
            lambda c: c["pending_owner_decisions"].append(
                copy.deepcopy(c["pending_owner_decisions"][0])
            ),
            lambda c: c["pending_owner_decisions"][0].update(status="APPROVED"),
            lambda c: c["policy_safety_baselines"].update(
                status="LIVE_COLLECTION_APPROVED"
            ),
            lambda c: c["policy_safety_baselines"]["decisions"]["Q07"][
                "outstanding_authorizations"
            ].clear(),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                altered = catalog()
                mutate(altered)
                with self.assertRaisesRegex(
                    QuestionnaireValidationError, "^candidate_catalog_policy_drift$"
                ):
                    validate_v1_field_catalog(altered)

    def test_catalog_does_not_authorize_live_data_collection_or_scoring(self):
        item = catalog()
        self.assertTrue(item["requirements"]["no_production_routes"])
        self.assertTrue(item["requirements"]["no_data_storage"])
        self.assertTrue(item["requirements"]["no_financial_scoring"])
        self.assertEqual(
            item["field_list_approval"]["status"], "OWNER_APPROVED_FOR_DEVELOPMENT"
        )


class CandidateFinancialShapeTests(unittest.TestCase):
    def test_income_flow_requires_exact_calendar_year_bounds_and_member(self):
        value = validate_v1_financial_candidate(
            **flow_options(), record=income_record()
        )
        self.assertEqual(value.section, "income")
        self.assertEqual(value.category, "EMPLOYMENT")
        self.assertIsInstance(value.value, ValidatedFlow)
        self.assertEqual(value.value.amount_cents, 12500)
        self.assertEqual(value.value.period_start, date(2026, 1, 1))
        self.assertEqual(str(value.member_id), SYNTHETIC_MEMBER)
        self.assertNotIn("12500", repr(value))
        with self.assertRaises(FrozenInstanceError):
            value.category = "HACKED"

    def test_expense_flow_not_coerced_to_annual_money(self):
        row = {
            "category": "HOUSING",
            "amount": 0,
            "period_start": "2026-05-01",
            "period_end": "2026-05-31",
        }
        value = validate_v1_financial_candidate(
            **flow_options("expenses"), record=row
        )
        self.assertEqual(value.value.amount_cents, 0)
        self.assertIsNone(value.member_id)

    def test_assets_and_liabilities_are_snapshots_not_flows(self):
        for section, category, owner_field in (
            ("assets", "CASH", "owner_member_id"),
            ("liabilities", "MORTGAGE", "responsible_member_id"),
        ):
            with self.subTest(section=section):
                row = {
                    "category": category,
                    "balance": 5000,
                    "as_of_date": "2026-11-01",
                    owner_field: SYNTHETIC_MEMBER,
                }
                result = validate_v1_financial_candidate(
                    catalog=catalog(), section=section, record=row,
                    approved_categories=(category,), min_cents=0, max_cents=100000,
                    authorized_member_ids=(SYNTHETIC_MEMBER,),
                )
                self.assertIsInstance(result.value, ValidatedBalance)
                self.assertEqual(result.value.as_of_date, date(2026, 11, 1))
                self.assertFalse(hasattr(result.value, "period_start"))

    def test_missing_or_unapproved_category_policy_is_rejected(self):
        for options in (None, (), [], ("OTHER_UNREVIEWED",), ("EMPLOYMENT", "EMPLOYMENT")):
            with self.subTest(options=options):
                parameters = flow_options()
                parameters["approved_categories"] = options
                with self.assertRaisesRegex(
                    QuestionnaireValidationError, "^candidate_category_policy_missing$"
                ):
                    validate_v1_financial_candidate(
                        **parameters, record=income_record()
                    )
        with self.assertRaisesRegex(
            QuestionnaireValidationError, "^candidate_category_not_allowed$"
        ):
            validate_v1_financial_candidate(
                **flow_options(), record=income_record(category="SUPPORT")
            )

    def test_no_inferred_money_bounds_or_period(self):
        for override, code in (
            ({"min_cents": None}, "money_bounds_not_configured"),
            ({"max_cents": None}, "money_bounds_not_configured"),
            ({"reporting_year": None}, "reporting_year_invalid"),
        ):
            with self.subTest(override=override):
                params = flow_options()
                params.update(override)
                with self.assertRaisesRegex(
                    QuestionnaireValidationError, "^" + code + "$"
                ):
                    validate_v1_financial_candidate(**params, record=income_record())

    def test_missing_values_and_unsupported_types_do_not_become_zero(self):
        for value, code in (
            (None, "amount_type_invalid"),
            ("12500", "amount_type_invalid"),
            (True, "amount_type_invalid"),
            (1.5, "amount_type_invalid"),
            (-1, "amount_out_of_range"),
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    QuestionnaireValidationError, "^" + code + "$"
                ):
                    validate_v1_financial_candidate(
                        **flow_options(), record=income_record(amount=value)
                    )

    def test_wrong_reporting_year_or_invalid_period_fails(self):
        for row, code in (
            (income_record(period_start="2025-12-31"), "flow_outside_reporting_year"),
            (income_record(period_end="2027-01-01"), "flow_outside_reporting_year"),
            (income_record(period_start="2026-12-31",
                           period_end="2026-01-01"), "flow_period_inverted"),
        ):
            with self.subTest(code=code):
                with self.assertRaisesRegex(
                    QuestionnaireValidationError, "^" + code + "$"
                ):
                    validate_v1_financial_candidate(**flow_options(), record=row)

    def test_exact_record_shape_prevents_overposting_and_partial_records(self):
        for row in (
            income_record(unknown_sensitive_field="never"),
            {key: val for key, val in income_record().items() if key != "amount"},
            ["EMPLOYMENT", 12500],
            {},
        ):
            with self.subTest(record_type=type(row)):
                with self.assertRaisesRegex(
                    QuestionnaireValidationError, "^candidate_record_shape_invalid$"
                ):
                    validate_v1_financial_candidate(**flow_options(), record=row)

    def test_member_scope_is_explicit_and_canonical(self):
        for member, ids, code in (
            (SYNTHETIC_MEMBER, None, "candidate_member_scope_missing"),
            (SYNTHETIC_MEMBER, (), "candidate_member_scope_missing"),
            (str(uuid4()), (SYNTHETIC_MEMBER,), "candidate_member_scope_denied"),
            (SYNTHETIC_MEMBER.upper(), (SYNTHETIC_MEMBER,), "candidate_member_invalid"),
            (None, (SYNTHETIC_MEMBER,), "candidate_member_invalid"),
        ):
            with self.subTest(code=code):
                params = flow_options()
                params["authorized_member_ids"] = ids
                with self.assertRaisesRegex(
                    QuestionnaireValidationError, "^" + code + "$"
                ):
                    validate_v1_financial_candidate(
                        **params, record=income_record(contributor_id=member)
                    )

    def test_member_scope_rejects_nil_malformed_and_duplicate_authorities(self):
        nil_id = "00000000-0000-0000-0000-000000000000"
        other = str(uuid4())
        cases = (
            (nil_id, (nil_id,), "candidate_member_scope_missing"),
            (SYNTHETIC_MEMBER, (nil_id, SYNTHETIC_MEMBER), "candidate_member_scope_missing"),
            (SYNTHETIC_MEMBER, ("invalid", SYNTHETIC_MEMBER), "candidate_member_scope_missing"),
            (SYNTHETIC_MEMBER, (SYNTHETIC_MEMBER.upper(),), "candidate_member_scope_missing"),
            (SYNTHETIC_MEMBER, (SYNTHETIC_MEMBER, SYNTHETIC_MEMBER), "candidate_member_scope_missing"),
            (SYNTHETIC_MEMBER, (other,), "candidate_member_scope_denied"),
            (nil_id, (SYNTHETIC_MEMBER,), "candidate_member_invalid"),
        )
        for member_id, allowed_ids, code in cases:
            with self.subTest(code=code, allowed_ids=allowed_ids):
                with self.assertRaises(QuestionnaireValidationError) as error:
                    validate_v1_financial_candidate(
                        **{**flow_options(), "authorized_member_ids": allowed_ids},
                        record=income_record(contributor_id=member_id),
                    )
                self.assertEqual(str(error.exception), code)
                self.assertNotIn(member_id, str(error.exception))

    def test_unapproved_sections_do_not_activate_consent_or_questionnaire(self):
        for section in ("consent", "school_questions", "household", None, "income "):
            with self.subTest(section=section):
                params = flow_options()
                params["section"] = section
                with self.assertRaisesRegex(
                    QuestionnaireValidationError, "^candidate_section_unsupported$"
                ):
                    validate_v1_financial_candidate(
                        **params, record=income_record()
                    )

    def test_errors_contain_only_stable_codes_never_financial_values(self):
        secret = "SYNTHETIC_PRIVATE_DATA_563829"
        with self.assertRaises(QuestionnaireValidationError) as error:
            validate_v1_financial_candidate(
                **flow_options(), record=income_record(category=secret)
            )
        self.assertEqual(str(error.exception), "candidate_category_not_allowed")
        self.assertNotIn(secret, str(error.exception))


if __name__ == "__main__":
    unittest.main()
