"""Durable fictional receipt, deliberately disconnected from production routes.

This service records a synthetic presentation milestone only. It does NOT
transition an AidApplication out of DRAFT or mean its 31-field questionnaire,
consent policy, financial documents, or submission requirements are satisfied.
"""
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404

from jireh.schools.access import require_household_access
from jireh.schools.models import AcademicYear
from jireh.schools.workspace_contributor_exception import contributor_review_pending
from .models import (
    AidApplication,
    AidApplicationStudent,
    SyntheticAidSubmission,
    SYNTHETIC_DISCLOSURE_VERSION,
)


@transaction.atomic
def record_synthetic_demo_submission(
    *, user, school_id, household_id, academic_year_id, accuracy_attested
):
    """One immutable audit receipt per authorized household annual draft.

    Authorization is independently derived from a durable active grant.
    PostgreSQL row locking serializes two family retries. A unique constraint
    also guards against duplicate rows on all supported database backends.
    This is never a payment or final legal application submission.
    """
    if getattr(settings, "JIREH_SYNTHETIC_SUBMISSION_ONLY", False) is not True:
        raise PermissionDenied("Synthetic submissions are disabled.")
    household = require_household_access(
        user, school_id=school_id, household_id=household_id
    )
    if accuracy_attested is not True:
        raise ValidationError("synthetic_attestation_required")
    year = AcademicYear.objects.for_school(household.school_id).filter(
        pk=academic_year_id
    ).first()
    if year is None:
        raise Http404("Draft not found.")

    draft = AidApplication.objects.for_school(household.school_id).select_for_update().filter(
        household_id=household.pk,
        academic_year_id=year.pk,
        status=AidApplication.STATUS_DRAFT,
    ).first()
    if draft is None:
        raise Http404("Draft not found.")
    if contributor_review_pending(draft.pk):
        raise ValidationError("synthetic_additional_review_pending")
    if not AidApplicationStudent.objects.for_school(household.school_id).filter(
        application_id=draft.pk,
        household_student__household_id=household.pk,
    ).exists():
        raise ValidationError("synthetic_child_selection_required")

    receipt, _created = SyntheticAidSubmission.objects.get_or_create(
        application=draft,
        defaults={
            "actor_user": user,
            "consent_version": SYNTHETIC_DISCLOSURE_VERSION,
            "accuracy_attested": True,
        },
    )
    return receipt


def read_synthetic_demo_submission(
    *, user, school_id, household_id, academic_year_id
):
    """Read back only the metadata of this household's fictional receipt."""
    if getattr(settings, "JIREH_SYNTHETIC_SUBMISSION_ONLY", False) is not True:
        raise PermissionDenied("Synthetic submissions are disabled.")
    household = require_household_access(
        user, school_id=school_id, household_id=household_id
    )
    receipt = SyntheticAidSubmission.objects.filter(
        application__school_id=household.school_id,
        application__household_id=household.pk,
        application__academic_year_id=academic_year_id,
    ).select_related("application").first()
    if receipt is None:
        raise Http404("Synthetic receipt not found.")
    return receipt
