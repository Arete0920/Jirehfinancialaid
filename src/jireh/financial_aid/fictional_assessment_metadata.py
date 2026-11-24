"""Report the presence of saved fictional records, without opening their contents."""

from dataclasses import dataclass
from uuid import UUID

from django.db.models import Exists, F, OuterRef
from django.http import Http404

from jireh.schools.access import require_aid_director_access
from jireh.schools.demo_seed import DEMO_SCHOOL_A_CODE
from jireh.schools.models import SchoolStaffAccess

from .models import AidApplication, AidApplicationStudent, FinancialDocument
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


def read_fictional_assessment_metadata(*, user, school_id, academic_year_id, application_id):
    """Return saved metadata for one authorized fictional draft, without calculating aid."""
    require_synthetic_questionnaire_preview()
    school = require_aid_director_access(user, school_id=school_id)
    documents = FinancialDocument.objects.for_school(school.pk).filter(
        application_id=OuterRef("pk"), household_id=OuterRef("household_id"),
    )
    students = AidApplicationStudent.objects.for_school(school.pk).filter(
        application_id=OuterRef("pk"),
        household_student__household_id=OuterRef("household_id"),
    )
    # Recheck the current grant and scope in the same statement as the metadata
    # read. A revocation between the preliminary check and this read must deny.
    values = AidApplication.objects.for_school(school.pk).filter(
        pk=application_id, academic_year_id=academic_year_id,
        academic_year__school_id=school.pk,
        household__school_id=school.pk, household__is_active=True,
        school__code=DEMO_SCHOOL_A_CODE, school__is_active=True,
        school__staff_access_grants__user_id=user.pk,
        school__staff_access_grants__user__is_active=True,
        school__staff_access_grants__role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        school__staff_access_grants__is_active=True,
        status=AidApplication.STATUS_DRAFT,
    ).values(
        "school_id", "academic_year_id",
        application_id=F("pk"),
        questionnaire_revision=F("synthetic_questionnaire__revision"),
        has_selected_student=Exists(students),
        has_active_document_metadata=Exists(documents.filter(state=FinancialDocument.STATE_ACTIVE)),
        has_pending_document_removal=Exists(documents.filter(state=FinancialDocument.STATE_DELETE_PENDING)),
    ).first()
    if values is None:
        raise Http404("Fictional assessment metadata unavailable.")
    return FictionalAssessmentMetadata(**values)
