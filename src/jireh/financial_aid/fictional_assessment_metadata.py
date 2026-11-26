"""Report the presence of saved fictional records, without opening their contents."""

from dataclasses import dataclass
from uuid import UUID

from django.db.models import Exists, F, OuterRef
from django.http import Http404

from jireh.schools.access import require_aid_director_access
from jireh.schools.demo_seed import DEMO_SCHOOL_A_CODE
from jireh.schools.models import SchoolStaffAccess

from .models import (
    AidApplication, AidApplicationStudent, FinancialDocument,
    SyntheticApplicationReview, SyntheticAidSubmission,
    SYNTHETIC_DISCLOSURE_VERSION, SYNTHETIC_REVIEW_VERSION,
)
from .synthetic_questionnaire_preview import require_synthetic_questionnaire_preview


@dataclass(frozen=True, slots=True, repr=False)
class FictionalAssessmentMetadata:
    """Record presence and revision only. These fields establish no verification or eligibility."""

    application_id: UUID
    school_id: UUID
    academic_year_id: UUID
    questionnaire_revision: int | None
    has_selected_student: bool
    has_active_document_metadata: bool
    has_pending_document_removal: bool
    has_historical_confirmation: bool
    has_confirmation_at_saved_revision: bool
    has_fictional_receipt: bool


def read_fictional_assessment_metadata(*, user, school_id, academic_year_id, application_id,
                                       fixture_scope=None):
    """Return saved metadata for one authorized fictional draft, without calculating aid."""
    if fixture_scope is None:
        require_synthetic_questionnaire_preview()
        case_scope = {"school__code": DEMO_SCHOOL_A_CODE}
    else:
        from jireh.runtime.customer_financial_policy import financial_scope_allowed

        if (type(fixture_scope) is not tuple or len(fixture_scope) != 3
                or fixture_scope[0] != school_id or fixture_scope[2] != academic_year_id
                or not financial_scope_allowed(*fixture_scope)):
            raise Http404("Fictional assessment metadata unavailable.")
        case_scope = {"household_id": fixture_scope[1]}
    school = require_aid_director_access(user, school_id=school_id)
    documents = FinancialDocument.objects.for_school(school.pk).filter(
        application_id=OuterRef("pk"), household_id=OuterRef("household_id"),
    )
    students = AidApplicationStudent.objects.for_school(school.pk).filter(
        application_id=OuterRef("pk"),
        household_student__household_id=OuterRef("household_id"),
    )
    reviews = SyntheticApplicationReview.objects.filter(
        questionnaire__application_id=OuterRef("pk"),
        disclosure_version=SYNTHETIC_REVIEW_VERSION,
    )
    receipts = SyntheticAidSubmission.objects.filter(
        application_id=OuterRef("pk"), accuracy_attested=True,
        consent_version=SYNTHETIC_DISCLOSURE_VERSION,
    )
    # Recheck the current grant and scope in the same statement as the metadata
    # read. A revocation between the preliminary check and this read must deny.
    values = AidApplication.objects.for_school(school.pk).filter(
        pk=application_id, academic_year_id=academic_year_id,
        academic_year__school_id=school.pk,
        household__school_id=school.pk, household__is_active=True,
        school__is_active=True,
        school__staff_access_grants__user_id=user.pk,
        school__staff_access_grants__user__is_active=True,
        school__staff_access_grants__role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        school__staff_access_grants__is_active=True,
        status=AidApplication.STATUS_DRAFT, **case_scope,
    ).values(
        "school_id", "academic_year_id",
        application_id=F("pk"),
        questionnaire_revision=F("synthetic_questionnaire__revision"),
        has_selected_student=Exists(students),
        has_active_document_metadata=Exists(documents.filter(state=FinancialDocument.STATE_ACTIVE)),
        has_pending_document_removal=Exists(documents.filter(state=FinancialDocument.STATE_DELETE_PENDING)),
        has_historical_confirmation=Exists(reviews),
        has_confirmation_at_saved_revision=Exists(reviews.filter(
            questionnaire_revision=F("questionnaire__revision"),
        )),
        has_fictional_receipt=Exists(receipts),
    ).first()
    if values is None:
        raise Http404("Fictional assessment metadata unavailable.")
    return FictionalAssessmentMetadata(**values)
