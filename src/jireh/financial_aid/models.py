"""Minimal annual household aid draft (no financial data or fee execution).

An application is unique per school, academic year and household. DRAFT is
the *only* valid lifecycle state until an authorized submission workflow,
consent, payment policy and audit semantics are specified and tested.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from jireh.schools.models import (
    AcademicYear,
    Household,
    HouseholdStudent,
    School,
    ScopedQuerySet,
    UUIDStampedModel,
)


class AidApplication(UUIDStampedModel):
    STATUS_DRAFT = "DRAFT"

    school = models.ForeignKey(
        School, on_delete=models.PROTECT, related_name="aid_applications"
    )
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.PROTECT, related_name="aid_applications"
    )
    household = models.ForeignKey(
        Household, on_delete=models.PROTECT, related_name="aid_applications"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="jireh_aid_drafts_created",
    )
    status = models.CharField(
        max_length=24,
        default=STATUS_DRAFT,
        choices=[(STATUS_DRAFT, "Draft")],
    )

    objects = ScopedQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "academic_year", "household"],
                name="jireh_aid_one_household_year",
            )
        ]

    def clean(self):
        super().clean()
        if self.school_id and self.academic_year_id:
            if self.academic_year.school_id != self.school_id:
                raise ValidationError(
                    {"academic_year": "Academic year belongs to another school."}
                )
        if self.school_id and self.household_id:
            if self.household.school_id != self.school_id:
                raise ValidationError(
                    {"household": "Household belongs to another school."}
                )


class ApplicationStudentQuerySet(models.QuerySet):
    def for_school(self, school_id):
        if not school_id:
            raise ValueError("school_id is required")
        return self.filter(
            application__school_id=school_id,
            household_student__household__school_id=school_id,
            household_student__student__school_id=school_id,
        )


class AidApplicationStudent(UUIDStampedModel):
    """An included child linked through a specific household-student record.

    The relationship is to HouseholdStudent, not just Student. A child who
    belongs to separate households therefore has separate selection records.
    This relation is not an authorization grant.
    """

    application = models.ForeignKey(
        AidApplication, on_delete=models.PROTECT, related_name="student_selections"
    )
    household_student = models.ForeignKey(
        HouseholdStudent, on_delete=models.PROTECT, related_name="aid_selections"
    )

    objects = ApplicationStudentQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["application", "household_student"],
                name="jireh_aid_application_student_unique",
            ),
        ]

    def clean(self):
        super().clean()
        if not self.application_id or not self.household_student_id:
            return
        application = self.application
        link = self.household_student
        if (
            link.household_id != application.household_id
            or link.household.school_id != application.school_id
            or link.student.school_id != application.school_id
            or application.academic_year.school_id != application.school_id
        ):
            raise ValidationError(
                "Selected child must belong to the application household and school."
            )
        if application.status != AidApplication.STATUS_DRAFT:
            raise ValidationError("Only a draft application may select students.")
