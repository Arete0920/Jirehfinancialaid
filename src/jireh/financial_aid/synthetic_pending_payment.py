"""Internal synthetic pending-payment persistence. No route or provider call."""

from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from jireh.runtime.customer_family_sessions import nonprivileged_family_account
from jireh.runtime.customer_financial_policy import financial_scope_allowed

from .fees import quote_application_submission_fee
from .models import (
    SYNTHETIC_HANDOFF_NOTICE_VERSION, SYNTHETIC_REVIEW_VERSION, SyntheticPendingPayment,
    SyntheticPrepaymentHandoff, SyntheticQuestionnaireDraft,
)
from .submission_contract import SubmissionContractError, validate_pending_payment_intent
from .synthetic_application_review import read_fictional_application_review
from .synthetic_prepayment_handoff import current_prepayment_handoff
from .synthetic_questionnaire_storage import _locked_draft


def _require_scope(user, school_id, household_id, academic_year_id):
    if not financial_scope_allowed(school_id, household_id, academic_year_id):
        raise Http404()
    if not nonprivileged_family_account(user):
        raise PermissionDenied()


def _invalidate(attempt):
    if attempt.invalidated_at is None:
        attempt.invalidated_at = timezone.now()
        SyntheticPendingPayment.objects.filter(pk=attempt.pk, invalidated_at__isnull=True).update(
            invalidated_at=attempt.invalidated_at, updated_at=attempt.invalidated_at,
        )


def _refresh(draft):
    active = SyntheticPendingPayment.objects.filter(application=draft, invalidated_at__isnull=True).first()
    if active is None:
        return None
    revision = SyntheticQuestionnaireDraft.objects.filter(application=draft).values_list("revision", flat=True).first()
    if current_prepayment_handoff(draft, revision, handoff_id=active.handoff_id) is None:
        _invalidate(active)
        return None
    return active


@transaction.atomic
def prepare_pending_payment(*, user, school_id, household_id, academic_year_id, handoff_id, disclosure_version):
    """Persist a current synthetic attempt or return the same authorized retry."""
    _require_scope(user, school_id, household_id, academic_year_id)
    if type(handoff_id) is not UUID or handoff_id.int == 0:
        raise SubmissionContractError("submission_handoff_required")
    review = read_fictional_application_review(
        user=user, school_id=school_id, household_id=household_id, academic_year_id=academic_year_id,
        key=settings.JIREH_SYNTHETIC_QUESTIONNAIRE_KEY,
    )
    draft = review["draft"]
    handoff = SyntheticPrepaymentHandoff.objects.filter(
        pk=handoff_id, confirmation=review["confirmation"],
        notice_version=SYNTHETIC_HANDOFF_NOTICE_VERSION,
    ).first()
    fee = quote_application_submission_fee(
        application_id=draft.pk, school_id=draft.school_id,
        household_id=draft.household_id, academic_year_id=draft.academic_year_id,
    )
    proposal = validate_pending_payment_intent(
        current_state=draft.status, accuracy_attested=review["confirmation"] is not None,
        consent_version=disclosure_version, disclosure_is_approved=disclosure_version == SYNTHETIC_REVIEW_VERSION,
        questionnaire_is_complete=not review["reasons"], authorized_household_scope=True,
        fee_obligation=fee, handoff_id=handoff_id, review_revision=review["revision"],
        handoff_is_current=handoff is not None and current_prepayment_handoff(
            draft, review["revision"], handoff_id=handoff_id,
        ) is not None,
    )
    prior = SyntheticPendingPayment.objects.filter(handoff_id=proposal.handoff_id).first()
    if prior is not None:
        if prior.invalidated_at is not None:
            raise SubmissionContractError("submission_pending_attempt_invalidated")
        return prior
    if _refresh(draft) is not None:
        raise SubmissionContractError("submission_pending_attempt_conflict")
    fee = proposal.fee_obligation
    return SyntheticPendingPayment.objects.create(
        application=draft, handoff_id=proposal.handoff_id, disclosure_version=proposal.consent_version,
        fee_amount_cents=fee.amount_cents, fee_currency=fee.currency, fee_obligation_key=fee.obligation_key,
    )


@transaction.atomic
def refresh_pending_payment(*, user, school_id, household_id, academic_year_id):
    """Expose only a current attempt and persist any observed invalidation."""
    _require_scope(user, school_id, household_id, academic_year_id)
    return _refresh(_locked_draft(user, school_id, household_id, academic_year_id))


@transaction.atomic
def withdraw_pending_payment(*, user, school_id, household_id, academic_year_id, attempt_id):
    """Invalidate the named attempt independently of later review or retries."""
    _require_scope(user, school_id, household_id, academic_year_id)
    draft = _locked_draft(user, school_id, household_id, academic_year_id)
    attempt = SyntheticPendingPayment.objects.filter(application=draft, pk=attempt_id).first()
    if attempt is None:
        raise Http404()
    _invalidate(attempt)
    return attempt
