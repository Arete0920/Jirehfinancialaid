"""School-authorized fictional $250 offered-aid service and family readback.

No production route, awards engine, tuition ledger, promise of funding,
financial-questionnaire answers or payments. This model is a synthetic test
artifact tied to an existing fictional submission receipt only.
"""
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404

from jireh.schools.access import require_aid_director_access, require_household_access
from jireh.schools.models import AcademicYear
from jireh.schools.workspace_contributor_exception import contributor_review_pending
from .models import (
    AidApplication, AidApplicationStudent,
    SyntheticAidOffer, SyntheticAidSubmission,
    SYNTHETIC_OFFER_AMOUNT_CENTS, SYNTHETIC_OFFER_BUCKET,
)
from .offer_contract import validate_officer_offer_intent


def _require_synthetic_mode():
    if getattr(settings, "JIREH_SYNTHETIC_SUBMISSION_ONLY", False) is not True:
        raise PermissionDenied("Synthetic offer services are disabled.")


@transaction.atomic
def record_synthetic_officer_offer(
    *, user, school_id, academic_year_id, application_id, student_id
):
    """Create exactly one fictional need offer for an authorized director.

    The school is authorized from the user's *active* aid-director grant, not
    request headers. The receipt is a synthetic-only event: AidApplication
    remains DRAFT and is never treated as a real submitted application.
    """
    _require_synthetic_mode()
    school = require_aid_director_access(user, school_id=school_id)
    application = (
        AidApplication.objects.for_school(school.pk)
        .select_for_update()
        .filter(
            pk=application_id,
            academic_year_id=academic_year_id,
            status=AidApplication.STATUS_DRAFT,
        )
        .first()
    )
    if application is None:
        raise Http404("Synthetic application not found.")
    if contributor_review_pending(application.pk):
        raise ValidationError("synthetic_action_unavailable")
    if not SyntheticAidSubmission.objects.filter(application_id=application.pk).exists():
        raise ValidationError("synthetic_receipt_required")
    selection = (
        AidApplicationStudent.objects.for_school(school.pk)
        .filter(
            application_id=application.pk,
            household_student__household_id=application.household_id,
            household_student__student_id=student_id,
        )
        .first()
    )
    if selection is None:
        raise Http404("Selected child not found.")
    # These trusted facts are derived from DB grants and the existing receipt.
    validate_officer_offer_intent(
        director_authorized=True,
        application_in_authorized_school_year=True,
        application_status="SUBMITTED",  # synthetic receipt state, not DB status
        student_selected_for_application=True,
        application_id=str(application.pk),
        student_id=str(student_id),
        bucket=SYNTHETIC_OFFER_BUCKET,
        amount_cents=SYNTHETIC_OFFER_AMOUNT_CENTS,
        min_cents=SYNTHETIC_OFFER_AMOUNT_CENTS,
        max_cents=SYNTHETIC_OFFER_AMOUNT_CENTS,
    )
    row, _created = SyntheticAidOffer.objects.get_or_create(
        student_selection=selection,
        defaults={
            "application": application,
            "actor_user": user,
            "bucket": SYNTHETIC_OFFER_BUCKET,
            "amount_cents": SYNTHETIC_OFFER_AMOUNT_CENTS,
        },
    )
    return row


@dataclass(frozen=True, slots=True, repr=False)
class SyntheticOfferReadback:
    application_id: str
    student_id: str
    bucket: str
    amount_cents: int
    status: str


def read_synthetic_director_offer(
    *, user, school_id, academic_year_id, application_id, student_id
) -> "SyntheticOfferReadback":
    """Independently read one saved fictional offer under an active school grant.

    Never infer a real submitted case, award or payment from this test record.
    Unknown cases, other schools, years, children and absent offers are 404.
    """
    _require_synthetic_mode()
    school = require_aid_director_access(user, school_id=school_id)
    application = (
        AidApplication.objects.for_school(school.pk)
        .filter(pk=application_id, academic_year_id=academic_year_id,
                status=AidApplication.STATUS_DRAFT)
        .first()
    )
    if application is None:
        raise Http404("Fictional offer unavailable.")
    offer = (
        SyntheticAidOffer.objects.filter(
            application_id=application.pk,
            student_selection__application_id=application.pk,
            student_selection__household_student__household_id=application.household_id,
            student_selection__household_student__student_id=student_id,
        )
        .select_related("student_selection__household_student")
        .first()
    )
    if offer is None:
        raise Http404("Fictional offer unavailable.")
    return SyntheticOfferReadback(
        application_id=str(offer.application_id),
        student_id=str(offer.student_selection.household_student.student_id),
        bucket=offer.bucket, amount_cents=offer.amount_cents,
        status="SYNTHETIC_OFFERED",
    )


def read_synthetic_family_offers(
    *, user, school_id, household_id, academic_year_id
) -> tuple[SyntheticOfferReadback, ...]:
    """Disclose only fictional offer metadata to its authorized household."""
    _require_synthetic_mode()
    household = require_household_access(
        user, school_id=school_id, household_id=household_id
    )
    if not AcademicYear.objects.for_school(household.school_id).filter(
        pk=academic_year_id
    ).exists():
        raise Http404("Synthetic year not found.")
    offers = (
        SyntheticAidOffer.objects.filter(
            application__school_id=household.school_id,
            application__household_id=household.pk,
            application__academic_year_id=academic_year_id,
        )
        .select_related("student_selection__household_student")
        .order_by("student_selection__household_student__student_id")
    )
    return tuple(
        SyntheticOfferReadback(
            application_id=str(offer.application_id),
            student_id=str(offer.student_selection.household_student.student_id),
            bucket=offer.bucket,
            amount_cents=offer.amount_cents,
            status="SYNTHETIC_OFFERED",
        )
        for offer in offers
    )
