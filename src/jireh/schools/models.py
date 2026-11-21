"""Independent school, household, and student identities.

No HTTP endpoints or access grants are provided by these models. A student's
link to two households does not expose either household's financial records.
Application services must use authenticated school scope and authorize each
household separately before reading sensitive data.
"""

import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q


class ScopedQuerySet(models.QuerySet):
    def for_school(self, school_id):
        if not school_id:
            raise ValueError("school_id is required")
        return self.filter(school_id=school_id)


class LinkQuerySet(models.QuerySet):
    def for_school(self, school_id):
        if not school_id:
            raise ValueError("school_id is required")
        return self.filter(
            household__school_id=school_id,
            student__school_id=school_id,
        )


class UUIDStampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        # Validate direct writes. Bulk/update/raw operations bypass this hook;
        # future APIs must not use those paths for linked identities.
        self.full_clean()
        return super().save(*args, **kwargs)


class School(UUIDStampedModel):
    code = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    timezone = models.CharField(max_length=64, default="UTC")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class AcademicYear(UUIDStampedModel):
    school = models.ForeignKey(
        School, on_delete=models.PROTECT, related_name="academic_years"
    )
    name = models.CharField(max_length=32)
    start_date = models.DateField()
    end_date = models.DateField()

    objects = ScopedQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "name"], name="jireh_school_year_unique"
            ),
            models.CheckConstraint(
                condition=Q(end_date__gt=F("start_date")),
                name="jireh_year_end_after_start",
            ),
        ]

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            raise ValidationError({"end_date": "Must be after start_date."})


class Household(UUIDStampedModel):
    school = models.ForeignKey(
        School, on_delete=models.PROTECT, related_name="households"
    )
    name = models.CharField(max_length=160)
    is_active = models.BooleanField(default=True)

    objects = ScopedQuerySet.as_manager()

    def __str__(self):
        return self.name


class Student(UUIDStampedModel):
    school = models.ForeignKey(
        School, on_delete=models.PROTECT, related_name="students"
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)

    objects = ScopedQuerySet.as_manager()

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class HouseholdStudent(UUIDStampedModel):
    """School-bounded link; not a household visibility/permission grant."""

    household = models.ForeignKey(
        Household, on_delete=models.PROTECT, related_name="student_links"
    )
    student = models.ForeignKey(
        Student, on_delete=models.PROTECT, related_name="household_links"
    )

    objects = LinkQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["household", "student"],
                name="jireh_household_student_unique",
            ),
        ]

    def clean(self):
        super().clean()
        if not self.household_id or not self.student_id:
            return
        if self.household.school_id != self.student.school_id:
            raise ValidationError(
                "Household and student must belong to the same school."
            )
