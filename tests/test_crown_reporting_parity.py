"""Regression acceptance for archived CROWN financial-aid reporting facts.

Historical invariants are a reference, not an approved reporting endpoint or
authorization to claim cash disbursement from an accepted award.
"""

import unittest

from legacy_crown.financial_aid_reporting import (
    FinancialAidDashboardIntegrityError,
    summarize_financial_aid_rows,
)


SCHOOL = "11111111-1111-1111-1111-111111111111"
OTHER_SCHOOL = "22222222-2222-2222-2222-222222222222"
YEAR = "33333333-3333-3333-3333-333333333333"
FAMILY = "44444444-4444-4444-4444-444444444444"
STUDENT = "55555555-5555-5555-5555-555555555555"


def application(status="SUBMITTED", **updates):
    row = {
        "family_id": FAMILY,
        "family__school_id": SCHOOL,
        "academic_year__school_id": SCHOOL,
        "status": status,
    }
    row.update(updates)
    return row


def award(status="ACCEPTED", cents=12500, **updates):
    row = {
        "student_id": STUDENT,
        "student__school_id": SCHOOL,
        "student__family_id": FAMILY,
        "student__family__school_id": SCHOOL,
        "academic_year__school_id": SCHOOL,
        "aid_application_id": "linked",
        "aid_application__school_id": SCHOOL,
        "aid_application__academic_year_id": YEAR,
        "aid_application__family_id": FAMILY,
        "decision_status": status,
        "awarded_cents": cents,
        "ledger_entry_id": None,
    }
    row.update(updates)
    return row


def facts(applications=None, awards=None):
    return summarize_financial_aid_rows(
        school_id=SCHOOL,
        year_id=YEAR,
        applications=[application()] if applications is None else applications,
        awards=[award()] if awards is None else awards,
    )


def valid_ledger():
    return {
        "ledger_entry_id": "entry",
        "ledger_entry__school_id": SCHOOL,
        "ledger_entry__academic_year_id": YEAR,
        "ledger_entry__student_id": STUDENT,
        "ledger_entry__family_id": FAMILY,
        "ledger_entry__amount_cents": -12500,
        "ledger_entry__is_reversal": False,
        "ledger_entry__source": "AID_AWARD",
        "ledger_entry__account__school_id": SCHOOL,
        "ledger_entry__account__code": "AID",
        "ledger_entry__reversal_of_id": None,
        "ledger_reversal_count": 0,
    }


class HistoricalFinancialAidReportingTests(unittest.TestCase):
    def test_true_zeros_with_no_records(self):
        self.assertEqual(
            facts([], []),
            {
                "submitted_applications": 0,
                "submitted_families": 0,
                "applications_requiring_review": 0,
                "accepted_award_records": 0,
                "accepted_award_face_value_cents": 0,
                "accepted_without_ledger_count": 0,
            },
        )

    def test_distinguishes_applications_families_and_award_records(self):
        rows = [
            application(status)
            for status in (
                "DRAFT",
                "SUBMITTED",
                "UNDER_REVIEW",
                "NEEDS_INFO",
                "APPROVED",
                "DENIED",
                "WITHDRAWN",
            )
        ]
        result = facts(rows, [award(), award("OFFERED", 5000), award("DECLINED", 3000)])
        self.assertEqual(result["submitted_applications"], 5)
        self.assertEqual(result["submitted_families"], 1)
        self.assertEqual(result["applications_requiring_review"], 3)
        self.assertEqual(result["accepted_award_records"], 1)
        self.assertEqual(result["accepted_award_face_value_cents"], 12500)
        self.assertEqual(result["accepted_without_ledger_count"], 1)

    def test_two_awards_do_not_double_count_one_family(self):
        result = facts([application()], [award(), award(cents=7500)])
        self.assertEqual(result["accepted_award_records"], 2)
        self.assertEqual(result["accepted_award_face_value_cents"], 20000)
        self.assertEqual(result["submitted_families"], 1)

    def test_rejects_cross_school_or_invalid_application_rows(self):
        cases = (
            {"family__school_id": OTHER_SCHOOL},
            {"academic_year__school_id": OTHER_SCHOOL},
            {"family_id": None},
            {"status": "INVENTED"},
        )
        for update in cases:
            with self.subTest(update=update):
                with self.assertRaises(FinancialAidDashboardIntegrityError):
                    facts([application(**update)], [])

    def test_rejects_cross_school_or_invalid_awards(self):
        cases = (
            {"student__school_id": OTHER_SCHOOL},
            {"student__family__school_id": OTHER_SCHOOL},
            {"academic_year__school_id": OTHER_SCHOOL},
            {"aid_application__school_id": OTHER_SCHOOL},
            {"aid_application__academic_year_id": OTHER_SCHOOL},
            {"aid_application__family_id": OTHER_SCHOOL},
            {"student__family_id": None},
            {"decision_status": "INVENTED"},
            {"awarded_cents": -1},
            {"awarded_cents": None},
        )
        for update in cases:
            with self.subTest(update=update):
                with self.assertRaises(FinancialAidDashboardIntegrityError):
                    facts([], [award(**update)])

    def test_accepted_zero_award_fails_closed(self):
        with self.assertRaises(FinancialAidDashboardIntegrityError):
            facts([], [award(cents=0)])

    def test_unposted_accepted_face_value_is_not_cash(self):
        result = facts([], [award()])
        self.assertEqual(result["accepted_award_face_value_cents"], 12500)
        self.assertEqual(result["accepted_without_ledger_count"], 1)
        result = facts([], [award(**valid_ledger())])
        self.assertEqual(result["accepted_without_ledger_count"], 0)

    def test_ledger_inconsistency_fails_closed(self):
        cases = (
            {"ledger_entry__school_id": OTHER_SCHOOL},
            {"ledger_entry__academic_year_id": OTHER_SCHOOL},
            {"ledger_entry__student_id": OTHER_SCHOOL},
            {"ledger_entry__family_id": OTHER_SCHOOL},
            {"ledger_entry__amount_cents": -12499},
            {"ledger_entry__is_reversal": True},
            {"ledger_entry__source": "PAYMENT"},
            {"ledger_entry__account__school_id": OTHER_SCHOOL},
            {"ledger_entry__account__code": "TUITION"},
            {"ledger_entry__reversal_of_id": "other-entry"},
            {"ledger_reversal_count": 1},
        )
        for update in cases:
            with self.subTest(update=update):
                ledger = valid_ledger()
                ledger.update(update)
                with self.assertRaises(FinancialAidDashboardIntegrityError):
                    facts([], [award(**ledger)])

    def test_reporting_reference_is_not_imported_by_runtime(self):
        # The original reference lives strictly under tests/, not src/jireh.
        from pathlib import Path
        source_root = Path(__file__).resolve().parents[1] / "src" / "jireh"
        for path in source_root.rglob("*.py"):
            body = path.read_text(encoding="utf-8")
            self.assertNotIn("legacy_crown.financial_aid_reporting", body)


if __name__ == "__main__":
    unittest.main()
