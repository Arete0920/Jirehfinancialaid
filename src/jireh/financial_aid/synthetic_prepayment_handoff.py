"""Explicit handoff of a confirmed draft in the disposable financial profile."""

from hmac import compare_digest
from re import fullmatch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404

from jireh.runtime.customer_family_sessions import nonprivileged_family_account
from jireh.runtime.customer_financial_policy import financial_scope_allowed
from jireh.schools.workspace_contributor_exception import contributor_review_pending

from .document_lifecycle import DocumentLifecycleError
from .models import SYNTHETIC_HANDOFF_NOTICE_VERSION, SyntheticPrepaymentHandoff
from .questionnaire_validation import QuestionnaireValidationError
from .synthetic_application_review import FictionalReviewError, read_fictional_application_review
from .synthetic_document_views import PrivateDocumentStorageError


@transaction.atomic
def record_prepayment_handoff(
    *, user, school_id, household_id, academic_year_id, expected_digest, notice_version,
):
    if not financial_scope_allowed(school_id, household_id, academic_year_id):
        raise Http404()
    if not nonprivileged_family_account(user):
        raise PermissionDenied()
    if (type(expected_digest) is not str or fullmatch(r"[0-9a-f]{64}", expected_digest) is None
            or type(notice_version) is not str or notice_version != SYNTHETIC_HANDOFF_NOTICE_VERSION):
        raise FictionalReviewError("prepayment_handoff_unavailable")
    state = read_fictional_application_review(
        user=user, school_id=school_id, household_id=household_id, academic_year_id=academic_year_id,
        key=settings.JIREH_SYNTHETIC_QUESTIONNAIRE_KEY,
    )
    if (not compare_digest(state["digest"], expected_digest)
            or state["confirmation"] is None or contributor_review_pending(state["draft"].pk)):
        raise FictionalReviewError("prepayment_handoff_unavailable")
    handoff, _ = SyntheticPrepaymentHandoff.objects.get_or_create(
        confirmation=state["confirmation"], defaults={"notice_version": notice_version},
    )
    return handoff


def current_prepayment_handoff(draft, questionnaire_revision, *, handoff_id=None, propagate_evidence_errors=False):
    """Return revalidated family evidence under the caller's school lock.

    A caller that invalidates evidence must distinguish unreadable evidence
    from a handoff that was confirmed stale or is no longer authorized.
    """
    school_id, household_id, academic_year_id = draft.school_id, draft.household_id, draft.academic_year_id
    if (questionnaire_revision is None or not financial_scope_allowed(school_id, household_id, academic_year_id)
            or contributor_review_pending(draft.pk)):
        return None
    handoffs = SyntheticPrepaymentHandoff.objects.filter(
        confirmation__questionnaire__application=draft,
        confirmation__questionnaire_revision=questionnaire_revision,
    )
    if handoff_id is not None:
        handoffs = handoffs.filter(pk=handoff_id)
    actors = get_user_model().objects.filter(pk__in=handoffs.values("confirmation__actor_user_id")).order_by("pk")
    for actor in actors:
        if not nonprivileged_family_account(actor):
            continue
        try:
            state = read_fictional_application_review(
                user=actor, school_id=school_id, household_id=household_id, academic_year_id=academic_year_id,
                key=settings.JIREH_SYNTHETIC_QUESTIONNAIRE_KEY,
            )
        except (Http404, PermissionDenied):
            continue
        except (FictionalReviewError, QuestionnaireValidationError, DocumentLifecycleError,
                PrivateDocumentStorageError, OSError):
            if propagate_evidence_errors:
                raise
            continue
        if state["confirmation"] is not None:
            handoff = handoffs.filter(confirmation=state["confirmation"]).first()
            if handoff is not None:
                return handoff
    return None
