"""Validate the design-only Jireh questionnaire catalog.

This file tests metadata, not applicant answers. It does not import Django,
add production routes, store financial records, or approve questionnaire policy.
"""

import json
import unittest
from pathlib import Path


CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "questionnaire_v1_field_catalog.json"
)
EXPECTED_SECTIONS = (
    "household",
    "income",
    "assets",
    "liabilities",
    "expenses",
    "school_questions",
    "consent",
)


def load_catalog():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


class QuestionnaireFieldCatalogDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def test_all_approved_sections_present_once(self):
        section_ids = [s["id"] for s in self.catalog["sections"]]
        self.assertEqual(section_ids, list(EXPECTED_SECTIONS))
        self.assertEqual(len(set(section_ids)), len(EXPECTED_SECTIONS))

    def test_catalog_is_explicitly_non_operational(self):
        self.assertEqual(
            self.catalog["schema_status"], "DESIGN_ONLY_NOT_APPROVED_FOR_COLLECTION"
        )
        self.assertEqual(self.catalog["schema_version"], "0.1.0")
        for flag in (
            "no_production_routes",
            "no_data_storage",
            "no_financial_scoring",
            "no_implicit_carry_forward",
            "no_inferred_household_access",
            "explicit_consent_for_reuse",
            "versioned_question_definitions",
            "audit_metadata_only",
        ):
            self.assertIs(self.catalog["requirements"][flag], True, flag)
        self.assertEqual(
            self.catalog["scope"],
            ["school_id", "academic_year_id", "household_id", "application_id"],
        )

    def test_fields_have_unique_scoped_paths_and_known_types(self):
        field_ids = []
        for section in self.catalog["sections"]:
            self.assertTrue(section["fields"], section["id"])
            self.assertEqual(section["lifecycle"], "candidate")
            for field in section["fields"]:
                path = field["id"]
                self.assertTrue(
                    path.startswith(section["id"] + ".")
                    or path.startswith(section["id"] + "[]."),
                    path,
                )
                self.assertIn(field["type"], self.catalog["types"], path)
                self.assertIn(
                    field["sensitivity"],
                    ("personal", "financial", "internal", "restricted"),
                    path,
                )
                self.assertTrue(field["required"], path)
                field_ids.append(path)
        self.assertEqual(len(field_ids), len(set(field_ids)))
        self.assertEqual(len(field_ids), 31)

    def test_money_flow_and_balance_have_distinct_time_semantics(self):
        types = self.catalog["types"]
        flow = types["money_flow"]
        balance = types["money_balance"]
        self.assertEqual(flow["unit"], "USD cents")
        self.assertEqual(balance["unit"], "USD cents")
        self.assertEqual(flow["wire_type"], "integer")
        self.assertEqual(balance["wire_type"], "integer")
        self.assertIs(flow["period_required"], True)
        self.assertIs(balance["as_of_date_required"], True)
        self.assertEqual(flow["min"], "PENDING_OWNER_POLICY")
        self.assertEqual(balance["min"], "PENDING_OWNER_POLICY")
        for section in self.catalog["sections"]:
            for field in section["fields"]:
                if section["id"] in ("income", "expenses") and field["type"].startswith("money_"):
                    self.assertEqual(field["type"], "money_flow")
                if section["id"] in ("assets", "liabilities") and field["type"].startswith("money_"):
                    self.assertEqual(field["type"], "money_balance")

    def test_consent_timestamp_server_generated_and_opt_in(self):
        fields = {
            f["id"]: f for s in self.catalog["sections"] for f in s["fields"]
        }
        self.assertEqual(fields["consent.attestation_timestamp"]["type"], "timestamp")
        self.assertEqual(
            self.catalog["types"]["timestamp"]["source"], "server"
        )
        self.assertEqual(fields["consent.prior_year_reuse"]["required"], "optional")
        self.assertIn("explicit_boolean", self.catalog["types"]["consent_decision"]["wire_type"])
        self.assertEqual(fields["consent.attestation_actor_id"]["required"], "server")

    def test_unapproved_policy_decisions_are_explicit(self):
        decisions = self.catalog["pending_owner_decisions"]
        self.assertEqual([d["id"] for d in decisions], [f"Q{i:02}" for i in range(1, 11)])
        self.assertTrue(all(d["topic"] and d["question"] for d in decisions))
        # No default tax year, retention period, custody access, scoring, or document mandate.
        self.assertFalse(any(key in self.catalog for key in ("production_enabled", "retention_days", "scoring_formula", "approved_tax_year")))


if __name__ == "__main__":
    unittest.main()
