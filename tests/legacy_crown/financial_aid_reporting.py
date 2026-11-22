"""Historical CROWN financial-aid reporting reference -- TEST ONLY.

Source: Arete0920/Crown-CSMS/backend/crown_api/dashboards/financial_aid_live.py
Commit: 46b56609fe18360299b08eabaa8bccdffb356a0e

Only the pure, database-independent aggregation function and its exception
are retained. The ORM producer and CROWN-specific database query are not ported.
CROWN statuses, ledger model and output labels are NOT approved as standalone
Jireh production contracts. Never import from src/jireh production modules.
"""

"""Canonical, school-scoped, current-year Financial Aid dashboard read model.

Counts are application/award *records*, not students or cash transactions.
Do not label an accepted award's face value as a disbursement or claim that
source-level live reads constitute hosted/financial certification.
"""


class FinancialAidDashboardIntegrityError(ValueError):
    """An aid record or current-year scope is inconsistent; do not show totals."""


def _same_id(left, right):
    return left is not None and right is not None and str(left) == str(right)


def _money(cents):
    return f"${cents // 100:,}.{cents % 100:02d}"


def summarize_financial_aid_rows(*, school_id, year_id, applications, awards):
    """Validate relationships before returning integer-only aggregates.

    The ORM producer supplies values()/related FK projections for one verified
    school and current academic year. No PII or individual record details leave
    this function. A partial, inconsistent total must never look authoritative.
    """
    allowed_app_statuses = {
        'DRAFT', 'SUBMITTED', 'UNDER_REVIEW', 'NEEDS_INFO',
        'APPROVED', 'DENIED', 'WITHDRAWN',
    }
    actionable = {'SUBMITTED', 'UNDER_REVIEW', 'NEEDS_INFO'}
    allowed_decisions = {'OFFERED', 'ACCEPTED', 'DECLINED'}

    submitted_count = 0
    requiring_review_count = 0
    accepted_awards_count = 0
    accepted_face_value_cents = 0
    accepted_without_ledger_count = 0
    submitted_families = set()

    for app in applications:
        if (
            not _same_id(app.get('family__school_id'), school_id)
            or not _same_id(app.get('academic_year__school_id'), school_id)
            or app.get('status') not in allowed_app_statuses
            or app.get('family_id') is None
        ):
            raise FinancialAidDashboardIntegrityError('Inconsistent aid application scope or status')
        status = app['status']
        if status not in {'DRAFT', 'WITHDRAWN'}:
            submitted_count += 1
            submitted_families.add(str(app['family_id']))
        if status in actionable:
            requiring_review_count += 1

    for award in awards:
        if (
            not _same_id(award.get('student__school_id'), school_id)
            or not _same_id(award.get('student__family__school_id'), school_id)
            or not _same_id(award.get('academic_year__school_id'), school_id)
            or award.get('student__family_id') is None
            or award.get('decision_status') not in allowed_decisions
            or type(award.get('awarded_cents')) is not int
            or award['awarded_cents'] < 0
        ):
            raise FinancialAidDashboardIntegrityError('Inconsistent aid award scope or amount')

        if award.get('aid_application_id') is not None and (
            not _same_id(award.get('aid_application__school_id'), school_id)
            or not _same_id(award.get('aid_application__academic_year_id'), year_id)
            or not _same_id(award.get('aid_application__family_id'), award['student__family_id'])
        ):
            raise FinancialAidDashboardIntegrityError('Award application and student family mismatch')

        # A linked ledger entry is additional evidence; validate it without
        # assuming that every historical accepted award was posted.
        if award.get('ledger_entry_id') is not None:
            reversal_count = award.get('ledger_reversal_count')
            if (
                not _same_id(award.get('ledger_entry__school_id'), school_id)
                or not _same_id(award.get('ledger_entry__academic_year_id'), year_id)
                or not _same_id(award.get('ledger_entry__student_id'), award['student_id'])
                or not _same_id(award.get('ledger_entry__family_id'), award['student__family_id'])
                or not _same_id(award.get('ledger_entry__account__school_id'), school_id)
                or award.get('ledger_entry__account__code') != 'AID'
                or award.get('ledger_entry__source') != 'AID_AWARD'
                or award.get('ledger_entry__is_reversal') is not False
                or award.get('ledger_entry__reversal_of_id') is not None
                or award.get('ledger_entry__amount_cents') != -award['awarded_cents']
                or type(reversal_count) is not int
                or reversal_count < 0 or reversal_count > 1
                or award['decision_status'] == 'OFFERED'
                or (award['decision_status'] == 'ACCEPTED' and reversal_count != 0)
                or (award['decision_status'] == 'DECLINED' and (reversal_count != 1 or award.get('ledger_reversal_validated') is not True))
            ):
                raise FinancialAidDashboardIntegrityError('Award ledger linkage requires reconciliation')

        if award['decision_status'] == 'ACCEPTED':
            if award['awarded_cents'] <= 0:
                raise FinancialAidDashboardIntegrityError('Accepted award must have positive face value')
            accepted_awards_count += 1
            accepted_face_value_cents += award['awarded_cents']
            if award.get('ledger_entry_id') is None:
                accepted_without_ledger_count += 1

    return {
        'submitted_applications': submitted_count,
        'submitted_families': len(submitted_families),
        'applications_requiring_review': requiring_review_count,
        'accepted_award_records': accepted_awards_count,
        'accepted_award_face_value_cents': accepted_face_value_cents,
        'accepted_without_ledger_count': accepted_without_ledger_count,
    }
