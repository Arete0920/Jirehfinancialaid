"""Minimal annual household aid draft (no financial data or fee execution).

An application is unique per school, academic year and household. DRAFT is
the *only* valid lifecycle state until an authorized submission workflow,
consent, payment policy and audit semantics are specified and tested.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

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


class AuditQuerySet(models.QuerySet):
    def for_school(self, school_id):
        if not school_id:
            raise ValueError("school_id is required")
        return self.filter(
            school_id=school_id,
            application__school_id=school_id,
            application__household__school_id=school_id,
        )


class AidAuditEvent(UUIDStampedModel):
    """Minimal, school-scoped event proof for authorized draft mutations.

    Records actor, application and event kind without income, documents or
    student names. Not a tamper-proof regulatory audit system: raw SQL and
    queryset writes can bypass model-level immutability protections.
    """

    ACTION_DRAFT_CREATED = "DRAFT_CREATED"
    ACTION_STUDENT_SELECTED = "STUDENT_SELECTED"

    school = models.ForeignKey(
        School, on_delete=models.PROTECT, related_name="jireh_aid_audit_events"
    )
    application = models.ForeignKey(
        AidApplication, on_delete=models.PROTECT, related_name="audit_events"
    )
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="jireh_aid_events_performed",
    )
    action = models.CharField(
        max_length=32,
        choices=[
            (ACTION_DRAFT_CREATED, "Household draft created"),
            (ACTION_STUDENT_SELECTED, "Student selected in draft"),
        ],
    )
    student_selection = models.ForeignKey(
        AidApplicationStudent,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_events",
    )

    objects = AuditQuerySet.as_manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(action="DRAFT_CREATED", student_selection__isnull=True)
                    | Q(action="STUDENT_SELECTED", student_selection__isnull=False)
                ),
                name="jireh_aid_event_action_selection",
            ),
            models.UniqueConstraint(
                fields=["application"],
                condition=Q(action="DRAFT_CREATED"),
                name="jireh_one_draft_created_event",
            ),
            models.UniqueConstraint(
                fields=["student_selection"],
                condition=Q(action="STUDENT_SELECTED"),
                name="jireh_one_student_selected_event",
            ),
        ]

    def clean(self):
        super().clean()
        if not self.application_id or not self.school_id:
            return
        application = self.application
        if (
            self.school_id != application.school_id
            or application.household.school_id != self.school_id
        ):
            raise ValidationError("Audit event school must match its application.")
        if self.action == self.ACTION_DRAFT_CREATED:
            if self.student_selection_id is not None:
                raise ValidationError("Draft creation cannot reference a selection.")
        elif self.action == self.ACTION_STUDENT_SELECTED:
            if not self.student_selection_id:
                raise ValidationError("Student selection event requires a selection.")
            if self.student_selection.application_id != application.pk:
                raise ValidationError("Audit selection belongs to another application.")
            if (
                self.student_selection.household_student.household_id
                != application.household_id
            ):
                raise ValidationError("Audit selection belongs to another household.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Existing audit records cannot be edited.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Audit records cannot be deleted through instances.")
