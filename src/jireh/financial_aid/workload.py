"""Pure, draft-only school workload aggregation; never a submission/award total.

Adapt CROWN's integrity-first, school-scoped reporting principles:
Arete0920/Crown-CSMS backend/crown_api/dashboards/financial_aid_live.py
at 46b56609fe18360299b08eabaa8bccdffb356a0e.
No Django, persistence, financial details, payment, or production routing.
"""
from uuid import UUID


class WorkloadIntegrityError(ValueError):
    """Inconsistent source rows or school/year relationships."""


def _uuid(value):
    return type(value) is UUID and value.int != 0


def _reject():
    raise WorkloadIntegrityError("draft_workload_integrity_invalid")


def summarize_draft_workload(*, school_id, academic_year_id, applications, selections):
    """Count household applications and selected links for one trusted school/year.

    Callers must verify director authorization and derive all rows from scoped ORM
    queries. This pure aggregator is not a permission check or a live dashboard.
    """
    if not _uuid(school_id) or not _uuid(academic_year_id):
        _reject()
    if type(applications) not in (list, tuple) or type(selections) not in (list, tuple):
        _reject()
    cases = {}
    households = set()
    for row in applications:
        if (
            type(row) is not dict
            or not _uuid(row.get("id"))
            or not _uuid(row.get("household_id"))
            or row.get("school_id") != school_id
            or row.get("academic_year_id") != academic_year_id
            or row.get("status") != "DRAFT"
            or row["id"] in cases
            or row["household_id"] in households
        ):
            _reject()
        cases[row["id"]] = row["household_id"]
        households.add(row["household_id"])

    selected_links = set()
    for row in selections:
        if type(row) is not dict:
            _reject()
        app_id = row.get("application_id")
        household_id = row.get("application__household_id")
        student_id = row.get("household_student__student_id")
        if (
            not _uuid(app_id)
            or not _uuid(household_id)
            or not _uuid(student_id)
            or row.get("application__school_id") != school_id
            or row.get("application__academic_year_id") != academic_year_id
            or row.get("household_student__household_id") != household_id
            or cases.get(app_id) != household_id
            or (app_id, student_id) in selected_links
        ):
            _reject()
        selected_links.add((app_id, student_id))

    return {
        "draft_application_records": len(cases),
        "distinct_draft_households": len(households),
        "selected_household_student_links": len(selected_links),
        "application_unit": "household_application_not_student",
        "selection_unit": "household_student_link_not_distinct_student",
        "financial_submissions_or_awards_included": False,
    }
