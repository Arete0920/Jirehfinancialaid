"""Authorized snapshot-bound rehearsal review; no submission or legal consent."""
import hashlib
import hmac
import json
from re import fullmatch
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction

from jireh.schools.models import HouseholdAccess
from .document_lifecycle import read_synthetic_document
from .fees import quote_application_submission_fee
from .fictional_school_questions import fictional_question_label, school_questions_for_draft
from .models import (
    AidApplicationStudent, FinancialDocument, SyntheticApplicationReview,
    SyntheticQuestionnaireDraft, SYNTHETIC_REVIEW_VERSION,
)
from .synthetic_document_views import _ALLOWED_FIXTURES, _backend
from .synthetic_questionnaire_storage import _guard, _locked_draft, _decrypt

_SECTIONS = ("income", "assets", "liabilities", "expenses")


class FictionalReviewError(ValueError):
    """Stable, nonsensitive review failure code."""


def _money(cents):
    return f"{Decimal(cents) / 100:,.2f}"


def _financial_sections(answers):
    return [
        {
            "name": section.title(),
            "rows": [
                {
                    "category": row["category"].replace("_", " ").title(),
                    "amount": _money(row["amount"] if section in ("income", "expenses") else row["balance"]),
                    "period": (row["period_start"] + " to " + row["period_end"]
                               if section in ("income", "expenses") else row["as_of_date"]),
                }
                for row in answers.get(section, [])
            ],
        }
        for section in _SECTIONS
    ]


def _review_state(*, user, school_id, household_id, academic_year_id, key):
    if (getattr(settings, "JIREH_SYNTHETIC_APPLICATION_REVIEW", False) is not True
            or getattr(settings, "JIREH_SYNTHETIC_DOCUMENTS_ONLY", False) is not True):
        raise PermissionDenied("Fictional review disabled.")
    _guard(key)
    draft = _locked_draft(user, school_id, household_id, academic_year_id)
    grant = HouseholdAccess.objects.get(household_id=draft.household_id, user=user, is_active=True)
    snapshot = SyntheticQuestionnaireDraft.objects.filter(application=draft).first()
    answers = _decrypt(snapshot, draft, key) if snapshot else {}
    sections = _financial_sections(answers)
    school_questions = school_questions_for_draft(draft, answers.get("school_questions", []))
    selections = list(AidApplicationStudent.objects.for_school(draft.school_id).filter(
        application=draft, household_student__household_id=draft.household_id,
    ).select_related("household_student__student").order_by("pk"))
    children = [selection.household_student.student for selection in selections]
    docs = list(FinancialDocument.objects.for_school(draft.school_id).filter(
        application=draft, household_id=draft.household_id,
    ).order_by("version"))
    active = [row for row in docs if row.state == FinancialDocument.STATE_ACTIVE]
    pending = any(row.state == FinancialDocument.STATE_DELETE_PENDING for row in docs)
    # A saved metadata row is not proof that encrypted content is retrievable.
    scope = dict(user=user, school_id=school_id, household_id=household_id,
                 academic_year_id=academic_year_id)
    for row in active:
        if read_synthetic_document(**scope, document_id=row.pk, backend=_backend()) not in _ALLOWED_FIXTURES:
            raise FictionalReviewError("review_document_unverified")
    reasons = []
    if not children:
        reasons.append("Select at least one child for this rehearsal.")
    if any(not section["rows"] for section in sections):
        reasons.append("Save at least one fictional row in each of the four financial sections.")
    if not active:
        reasons.append("Save at least one fictional supporting PDF.")
    if pending:
        reasons.append("Resolve pending document removal before confirming.")
    # Digest covers only metadata, not income or document contents. Include
    # revision identity, selection records, document history and grant epoch.
    identity = [
        SYNTHETIC_REVIEW_VERSION, str(draft.pk), str(user.pk), str(grant.pk),
        grant.updated_at.isoformat(),
        [str(snapshot.pk), snapshot.revision] if snapshot else None,
        [str(row.pk) for row in selections],
        [[str(row.pk), row.version, row.state] for row in docs],
    ]
    digest = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode("utf-8")).hexdigest()
    confirmation = None
    if snapshot and not reasons:
        confirmation = SyntheticApplicationReview.objects.filter(
            questionnaire=snapshot, actor_user=user, state_digest=digest,
        ).first()
    fee = quote_application_submission_fee(
        application_id=draft.pk, school_id=draft.school_id,
        household_id=draft.household_id, academic_year_id=draft.academic_year_id,
    )
    return {
        "draft": draft, "snapshot": snapshot, "digest": digest,
        "revision": snapshot.revision if snapshot else 0,
        "children": children, "sections": sections, "documents": active,
        "school_questions": [
            {"label": fictional_question_label(answer.definition), "version": answer.definition.version,
             "value": ("Yes" if answer.value else "No") if type(answer.value) is bool else answer.value}
            for answer in school_questions.saved
        ],
        "reasons": reasons, "confirmation": confirmation,
        "fee": _money(fee.amount_cents),
        "version": SYNTHETIC_REVIEW_VERSION,
    }


@transaction.atomic
def read_fictional_application_review(**scope):
    return _review_state(**scope)


@transaction.atomic
def confirm_fictional_application_review(*, expected_digest, reviewed, **scope):
    state = _review_state(**scope)
    if (
        type(expected_digest) is not str
        or fullmatch(r"[0-9a-f]{64}", expected_digest) is None
        or not hmac.compare_digest(state["digest"], expected_digest)
    ):
        raise FictionalReviewError("review_state_changed")
    if state["reasons"]:
        raise FictionalReviewError("review_incomplete")
    if reviewed is not True:
        raise FictionalReviewError("review_confirmation_required")
    record, _ = SyntheticApplicationReview.objects.get_or_create(
        questionnaire=state["snapshot"], actor_user=scope["user"],
        state_digest=state["digest"],
        defaults={"questionnaire_revision": state["revision"],
                  "disclosure_version": state["version"]},
    )
    return record
