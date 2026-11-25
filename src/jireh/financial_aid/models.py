"""Minimal annual household aid draft (no financial data or fee execution).

An application is unique per school, academic year and household. DRAFT is
the *only* valid lifecycle state until an authorized submission workflow,
consent, payment policy and audit semantics are specified and tested.
"""

import uuid

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


# This is a *synthetic demonstration receipt*, not the annual application's
# legally accepted SUBMITTED state. It does not authorize financial collection.
SYNTHETIC_DISCLOSURE_VERSION = "synthetic-demo-v1"


class SyntheticAidSubmission(UUIDStampedModel):
    """Immutable, one-per-application evidence for a fictional submission.

    Real AidApplication.status remains DRAFT; production routing never includes
    this workflow. Only actor, a fixed fictional disclosure version, and UTC
    creation time are retained; no financial answers or private child details.
    """

    application = models.OneToOneField(
        AidApplication, on_delete=models.PROTECT,
        related_name="synthetic_submission",
    )
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="jireh_synthetic_submissions",
    )
    consent_version = models.CharField(max_length=64)
    accuracy_attested = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(accuracy_attested=True),
                name="jireh_synthetic_attested_true",
            ),
            models.CheckConstraint(
                condition=Q(consent_version="synthetic-demo-v1"),
                name="jireh_synthetic_disclosure_v1",
            ),
        ]

    def clean(self):
        super().clean()
        if self.consent_version != SYNTHETIC_DISCLOSURE_VERSION:
            raise ValidationError("Only the fixed synthetic disclosure is supported.")
        if self.accuracy_attested is not True:
            raise ValidationError("Explicit synthetic attestation is required.")
        if not self.application_id or not self.actor_user_id:
            return
        from jireh.schools.models import HouseholdAccess

        app = self.application
        if (
            app.status != AidApplication.STATUS_DRAFT
            or not app.school.is_active
            or not app.household.is_active
            or not app.student_selections.exists()
            or not self.actor_user.is_active
            or not HouseholdAccess.objects.filter(
                household_id=app.household_id,
                user_id=self.actor_user_id,
                is_active=True,
            ).exists()
        ):
            raise ValidationError("Synthetic submission requires an authorized draft.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Synthetic submission evidence is immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Synthetic submission evidence cannot be deleted.")


SYNTHETIC_OFFER_AMOUNT_CENTS = 25_000
SYNTHETIC_OFFER_BUCKET = "need"


class SyntheticAidOffer(UUIDStampedModel):
    """One fictional $250 offered-aid record per selected child.

    NOT a real AidAward, allocation, award acceptance, tuition credit, payment,
    ledger or commitment of school funds. Only used by synthetic test services.
    """

    application = models.ForeignKey(
        AidApplication, on_delete=models.PROTECT, related_name="synthetic_offers",
    )
    student_selection = models.OneToOneField(
        AidApplicationStudent, on_delete=models.PROTECT,
        related_name="synthetic_offer",
    )
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="jireh_synthetic_offers_created",
    )
    bucket = models.CharField(max_length=16, default=SYNTHETIC_OFFER_BUCKET)
    amount_cents = models.PositiveIntegerField(default=SYNTHETIC_OFFER_AMOUNT_CENTS)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(bucket="need"),
                name="jireh_syn_offer_bucket",
            ),
            models.CheckConstraint(
                condition=Q(amount_cents=25000),
                name="jireh_syn_offer_fixed_amount",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.bucket != SYNTHETIC_OFFER_BUCKET
            or type(self.amount_cents) is not int
            or self.amount_cents != SYNTHETIC_OFFER_AMOUNT_CENTS
        ):
            raise ValidationError("Only the fixed $250 synthetic example is supported.")
        if not self.application_id or not self.student_selection_id or not self.actor_user_id:
            return
        from jireh.schools.models import SchoolStaffAccess

        app = self.application
        selection = self.student_selection
        if (
            selection.application_id != app.pk
            or app.status != AidApplication.STATUS_DRAFT
            or not app.school.is_active
            or not self.actor_user.is_active
            or not SyntheticAidSubmission.objects.filter(application_id=app.pk).exists()
            or not SchoolStaffAccess.objects.filter(
                school_id=app.school_id,
                user_id=self.actor_user_id,
                role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
                is_active=True,
            ).exists()
        ):
            raise ValidationError("Synthetic offer requires a submitted demo case and director.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Synthetic offer evidence is immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Synthetic offered aid cannot be deleted.")


class FinancialDocument(UUIDStampedModel):
    """School-bound document metadata; no file bytes or original file name.

    This model is currently reachable only through a synthetic-only service,
    not a runtime URL. The opaque object identifier is never exposed as a URL.
    """

    STATE_ACTIVE = "ACTIVE"
    STATE_DELETE_PENDING = "DELETE_PENDING"
    STATE_DELETED = "DELETED"
    STATES = [
        (STATE_ACTIVE, "Scanned"),
        (STATE_DELETE_PENDING, "Pending secure removal"),
        (STATE_DELETED, "Removed"),
    ]

    school = models.ForeignKey(School, on_delete=models.PROTECT)
    household = models.ForeignKey(Household, on_delete=models.PROTECT)
    application = models.ForeignKey(AidApplication, on_delete=models.PROTECT, related_name="document_records")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    object_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    request_key = models.UUIDField(unique=True, editable=False)
    version = models.PositiveIntegerField()
    category = models.CharField(max_length=48)
    detected_media_type = models.CharField(max_length=96)
    byte_count = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    state = models.CharField(max_length=16, choices=STATES, default=STATE_ACTIVE)
    deleted_at = models.DateTimeField(null=True, blank=True)
    objects = ScopedQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["application", "version"], name="jireh_document_app_version_unique"
            ),
            models.CheckConstraint(
                condition=Q(byte_count__gt=0), name="jireh_document_positive_bytes"
            ),
            models.CheckConstraint(
                condition=Q(version__gt=0), name="jireh_document_positive_version"
            ),
        ]

    def clean(self):
        super().clean()
        if not self.school_id or not self.household_id or not self.application_id:
            return
        app = self.application
        if (
            app.school_id != self.school_id
            or app.household_id != self.household_id
            or app.status != AidApplication.STATUS_DRAFT
            or self.household.school_id != self.school_id
            or app.academic_year.school_id != self.school_id
        ):
            raise ValidationError("Document metadata scope mismatch.")
        if self._state.adding:
            return
        old = type(self).objects.filter(pk=self.pk).values(
            "school_id", "household_id", "application_id", "created_by_id",
            "object_key", "request_key", "version", "category",
            "detected_media_type", "byte_count", "sha256",
        ).first()
        if old and any(getattr(self, name) != old[name] for name in old):
            raise ValidationError("Document identity and content metadata are immutable.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Documents require the scoped secure-delete service.")


class FinancialDocumentEvent(UUIDStampedModel):
    """Metadata-only document lifecycle event; excludes file values and names."""

    ACTION_CREATED = "CREATED"
    ACTION_DELETED = "DELETED"
    document = models.ForeignKey(FinancialDocument, on_delete=models.PROTECT, related_name="events")
    school = models.ForeignKey(School, on_delete=models.PROTECT)
    actor_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(
        max_length=16,
        choices=[(ACTION_CREATED, "Created"), (ACTION_DELETED, "Deleted")],
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["document", "action"], name="jireh_document_once_per_event"
            )
        ]

    def clean(self):
        super().clean()
        if self.document_id and self.school_id and self.document.school_id != self.school_id:
            raise ValidationError("Document audit school mismatch.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Document audit events are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Document audit events are append-only.")


class SyntheticQuestionnaireDraft(UUIDStampedModel):
    """One encrypted, disposable financial-answer snapshot per annual draft.

    No legal consent, verification, live collection or scoring is represented.
    The separate revision events contain metadata only, not prior answers.
    """

    application = models.OneToOneField(
        AidApplication, on_delete=models.PROTECT,
        related_name="synthetic_questionnaire",
    )
    revision = models.PositiveIntegerField()
    ciphertext = models.BinaryField(max_length=32796, editable=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(revision__gt=0), name="jireh_syn_questionnaire_revision_positive",
            ),
        ]


class SyntheticQuestionnaireEvent(UUIDStampedModel):
    """Append-only actor and revision evidence; no values or consent."""

    questionnaire = models.ForeignKey(
        SyntheticQuestionnaireDraft, on_delete=models.PROTECT, related_name="events",
    )
    actor_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    revision = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["questionnaire", "revision"], name="jireh_syn_questionnaire_event_unique",
            ),
            models.CheckConstraint(
                condition=Q(revision__gt=0), name="jireh_syn_questionnaire_event_positive",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Questionnaire revision evidence is immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Questionnaire revision evidence is immutable.")

SYNTHETIC_REVIEW_VERSION = "fictional-review-v1"


class SyntheticApplicationReview(UUIDStampedModel):
    """Immutable rehearsal confirmation, never consent or final submission."""

    questionnaire = models.ForeignKey(
        SyntheticQuestionnaireDraft, on_delete=models.PROTECT, related_name="reviews",
    )
    actor_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    questionnaire_revision = models.PositiveIntegerField()
    state_digest = models.CharField(max_length=64)
    disclosure_version = models.CharField(max_length=32, default=SYNTHETIC_REVIEW_VERSION)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["questionnaire", "actor_user", "state_digest"],
                name="jireh_syn_review_actor_state_unique",
            ),
            models.CheckConstraint(
                condition=Q(questionnaire_revision__gt=0, disclosure_version="fictional-review-v1"),
                name="jireh_syn_review_revision_version",
            ),
        ]

    def clean(self):
        super().clean()
        from re import fullmatch
        from jireh.schools.models import HouseholdAccess

        if not isinstance(self.state_digest, str) or not fullmatch(r"[0-9a-f]{64}", self.state_digest):
            raise ValidationError("Invalid fictional review evidence.")
        if not self.questionnaire_id or not self.actor_user_id:
            return
        snapshot = self.questionnaire
        draft = snapshot.application
        if (
            self.questionnaire_revision != snapshot.revision
            or draft.status != AidApplication.STATUS_DRAFT
            or draft.household.school_id != draft.school_id
            or draft.academic_year.school_id != draft.school_id
            or not draft.school.is_active
            or not draft.household.is_active
            or not self.actor_user.is_active
            or not HouseholdAccess.objects.filter(
                household_id=draft.household_id, user_id=self.actor_user_id, is_active=True,
            ).exists()
        ):
            raise ValidationError("Invalid fictional review scope.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Fictional review evidence is immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Fictional review evidence is immutable.")


class FictionalSchoolPlanRevision(UUIDStampedModel):
    """A saved tuition, capacity and budget revision for a disposable school year."""

    school = models.ForeignKey(School, on_delete=models.PROTECT)
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    revision = models.PositiveIntegerField()
    plan_payload = models.JSONField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["academic_year", "revision"], name="jireh_school_plan_year_revision"),
            models.CheckConstraint(condition=Q(revision__gt=0), name="jireh_school_plan_positive_revision"),
        ]

    def as_plan(self):
        from .annual_school_plan import AnnualSchoolPlanError, FictionalAnnualSchoolPlan, FictionalGradeBand

        try:
            payload = dict(self.plan_payload)
            grade_bands = payload.pop("grade_bands")
            if type(self.plan_payload) is not dict or type(grade_bands) is not list:
                raise TypeError
            return FictionalAnnualSchoolPlan(
                grade_bands=tuple(FictionalGradeBand(**band) for band in grade_bands), **payload,
            )
        except (AnnualSchoolPlanError, KeyError, TypeError, ValueError):
            raise ValidationError({"plan_payload": "Invalid fictional school plan."}) from None

    def clean(self):
        super().clean()
        self.as_plan()
        if self.school_id and self.academic_year_id and self.academic_year.school_id != self.school_id:
            raise ValidationError({"academic_year": "Academic year belongs to another school."})

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Fictional school plan revisions are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Fictional school plan revisions are immutable.")


class FictionalNeedDecision(UUIDStampedModel):
    """Append-only, nonbinding household need decision in the disposable rehearsal."""

    application = models.ForeignKey(AidApplication, on_delete=models.PROTECT)
    questionnaire = models.ForeignKey(SyntheticQuestionnaireDraft, on_delete=models.PROTECT)
    questionnaire_revision = models.PositiveIntegerField()
    plan = models.ForeignKey(FictionalSchoolPlanRevision, on_delete=models.PROTECT)
    receipt = models.ForeignKey(SyntheticAidSubmission, on_delete=models.PROTECT)
    actor_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    revision = models.PositiveIntegerField()
    amount_cents = models.PositiveBigIntegerField()
    need_cents = models.PositiveBigIntegerField()
    remaining_budget_cents = models.PositiveBigIntegerField()
    calculation_version = models.CharField(max_length=64)
    dataset_sha256 = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["application", "revision"], name="jireh_need_decision_revision"),
            models.CheckConstraint(
                condition=Q(revision__gt=0, questionnaire_revision__gt=0)
                & (Q(revision__gt=1) | Q(amount_cents__gt=0))
                & Q(amount_cents__lte=models.F("need_cents"))
                & Q(calculation_version="fictional-regional-need-v1"),
                name="jireh_need_decision_valid",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Fictional need decisions are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Fictional need decisions are immutable.")


class FictionalIncomeEvidenceReview(UUIDStampedModel):
    """Immutable acceptance of a versioned server-supplied fictional evidence reference."""

    questionnaire = models.ForeignKey(SyntheticQuestionnaireDraft, on_delete=models.PROTECT)
    questionnaire_revision = models.PositiveIntegerField()
    plan = models.ForeignKey(FictionalSchoolPlanRevision, on_delete=models.PROTECT)
    actor_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    evidence_id = models.UUIDField()
    accepted_on = models.DateField()
    reassess_on = models.DateField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["questionnaire", "questionnaire_revision", "plan", "evidence_id"],
                name="jireh_fictional_income_review_scope",
            ),
            models.CheckConstraint(
                condition=Q(questionnaire_revision__gt=0, reassess_on__gt=models.F("accepted_on")),
                name="jireh_fictional_income_review_valid",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Fictional income evidence reviews are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Fictional income evidence reviews are immutable.")
