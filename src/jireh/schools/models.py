"""Independent school, household, and student identities.

No HTTP endpoints or access grants are provided by these models. A student's
link to two households does not expose either household's financial records.
Application services must use authenticated school scope and authorize each
household separately before reading sensitive data.
"""

import uuid

from django.conf import settings
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




class GrantImmutableBinding(models.Model):
    """Protect a persisted grant's identity through ordinary Django saves.

    Privileged database writers and QuerySet.update() bypass clean(); on
    PostgreSQL, migration schools.0004 also blocks direct UPDATE and DELETE.
    The active flag may be changed for revocation; authorization to change
    that flag and to create grants is a separate, not-yet-exposed workflow.
    """

    IMMUTABLE_FIELDS = ()

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_grant_id = self.pk

    def clean(self):
        super().clean()
        if self._state.adding:
            return
        if self.pk != self._original_grant_id:
            raise ValidationError({"id": "A persisted grant ID is immutable."})
        previous = type(self).objects.filter(pk=self.pk).values(
            *self.IMMUTABLE_FIELDS
        ).first()
        if previous is None:
            return
        changed = {
            name: "A grant's existing identity cannot be reassigned."
            for name in self.IMMUTABLE_FIELDS
            if getattr(self, name) != previous[name]
        }
        if changed:
            raise ValidationError(changed)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Access grants cannot be deleted; revoke them using is_active."
        )

class HouseholdAccess(GrantImmutableBinding, UUIDStampedModel):
    """Explicit user-to-household grant. Never inferred from a shared child.

    Grants are provisioned by trusted internal services; no self-enrollment or
    public write endpoint is provided here. A user's school access through this
    record is limited to this household, not all households at that school.
    """

    IMMUTABLE_FIELDS = ("id", "created_at", "household_id", "user_id")

    household = models.ForeignKey(
        Household, on_delete=models.PROTECT, related_name="access_grants"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="jireh_household_access",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["household", "user"],
                name="jireh_household_access_unique",
            )
        ]


class SchoolStaffAccess(GrantImmutableBinding, UUIDStampedModel):
    """Explicit aid-director role at exactly one school.

    No self-service provisioning or implicit superuser/email-based privilege.
    Future staff roles require a separately approved permission matrix.
    """

    ROLE_AID_DIRECTOR = "AID_DIRECTOR"
    IMMUTABLE_FIELDS = ("id", "created_at", "school_id", "user_id", "role")

    school = models.ForeignKey(
        School, on_delete=models.PROTECT, related_name="staff_access_grants"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="jireh_school_staff_access",
    )
    role = models.CharField(
        max_length=32,
        choices=[(ROLE_AID_DIRECTOR, "Financial aid director")],
    )
    is_active = models.BooleanField(default=True)

    objects = ScopedQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "user"],
                name="jireh_staff_access_school_user_unique",
            ),
            models.CheckConstraint(
                condition=Q(role="AID_DIRECTOR"),
                name="jireh_staff_aid_director_only",
            ),
        ]


class GrantTransitionEvent(UUIDStampedModel):
    """DB-captured grant status history; not human operator authorization.

    On PostgreSQL the transition trigger writes events atomically for grant
    INSERT and actual is_active changes, even when QuerySet.update() is used.
    The DB role is NOT the identity of a human operator. No public API exists.
    """

    KIND_HOUSEHOLD = "HOUSEHOLD"
    KIND_STAFF = "STAFF"
    ACTION_CREATED = "CREATED"
    ACTION_REVOKED = "REVOKED"
    ACTION_REACTIVATED = "REACTIVATED"

    school = models.ForeignKey(
        School, on_delete=models.PROTECT, related_name="grant_transition_events"
    )
    grant_kind = models.CharField(
        max_length=16,
        choices=[(KIND_HOUSEHOLD, "Household"), (KIND_STAFF, "Staff")],
    )
    grant_id = models.UUIDField()
    scope_id = models.UUIDField()
    subject_user_id = models.CharField(max_length=128)
    action = models.CharField(
        max_length=16,
        choices=[
            (ACTION_CREATED, "Created"),
            (ACTION_REVOKED, "Revoked"),
            (ACTION_REACTIVATED, "Reactivated"),
        ],
    )
    is_active = models.BooleanField()
    database_role = models.CharField(max_length=128)

    objects = ScopedQuerySet.as_manager()

    class Meta:
        indexes = [
            models.Index(
                fields=["school", "grant_id"],
                name="jireh_grant_event_lookup",
            )
        ]

    def save(self, *args, **kwargs):
        raise ValidationError(
            "Grant transition events are written by PostgreSQL triggers only."
        )

    def delete(self, *args, **kwargs):
        raise ValidationError("Grant transition events are append-only.")


class SchoolGrantDecisionEvent(UUIDStampedModel):
    """Actor-attributed record of authorized school access decisions.

    Unlike database-role-only GrantTransitionEvent, actor_user records the
    authenticated principal that passed the school-scoped director check.
    This log covers only authorized calls through grant_admin. PostgreSQL prevents
    ordinary raw SQL updates/deletes; privileged DB roles remain a limit.
    """

    KIND_HOUSEHOLD = "HOUSEHOLD"
    KIND_STAFF = "STAFF"
    ACTION_CREATED = "CREATED"
    ACTION_REVOKED = "REVOKED"

    school = models.ForeignKey(
        School, on_delete=models.PROTECT, related_name="grant_decisions"
    )
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="jireh_grant_decisions_performed",
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="jireh_grant_decisions_received",
    )
    grant_kind = models.CharField(
        max_length=16,
        choices=[(KIND_HOUSEHOLD, "Household"), (KIND_STAFF, "Staff")],
    )
    grant_id = models.UUIDField()
    scope_id = models.UUIDField()
    action = models.CharField(
        max_length=16,
        choices=[(ACTION_CREATED, "Created"), (ACTION_REVOKED, "Revoked")],
    )

    objects = ScopedQuerySet.as_manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(grant_kind__in=["HOUSEHOLD", "STAFF"]),
                name="jireh_operator_valid_kind",
            ),
            models.CheckConstraint(
                condition=Q(action__in=["CREATED", "REVOKED"]),
                name="jireh_operator_action_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "grant_id"], name="jireh_operator_grant_lookup"
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Existing grant decision records cannot be edited.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Grant decision records cannot be deleted.")



class HouseholdInvitation(UUIDStampedModel):
    """Pending household invitation. This is NOT an access grant.

    Only a SHA-256 digest of a high-entropy one-time secret is persisted.
    No public redemption or delivery routes are enabled by this model.
    """

    school = models.ForeignKey(
        School, on_delete=models.PROTECT, related_name="household_invitations"
    )
    household = models.ForeignKey(
        Household, on_delete=models.PROTECT, related_name="invitations"
    )
    email = models.EmailField(max_length=254)
    token_digest = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="jireh_household_invitations_issued",
    )
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    redeemed_at = models.DateTimeField(null=True, blank=True)
    redeemed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="jireh_household_invitations_redeemed",
    )

    objects = ScopedQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["household", "email"],
                condition=Q(revoked_at__isnull=True, redeemed_at__isnull=True),
                name="jireh_open_household_invite",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "household"], name="jireh_invite_school_house"
            )
        ]

    def clean(self):
        super().clean()
        if self.school_id and self.household_id:
            if self.household.school_id != self.school_id:
                raise ValidationError(
                    "Invitation school must match the household's school."
                )
        if self.email and self.email != self.email.strip().casefold():
            raise ValidationError({"email": "Use a normalized email address."})
        if self._state.adding:
            return
        previous = type(self).objects.filter(pk=self.pk).values(
            "id", "created_at", "school_id", "household_id", "email",
            "token_digest", "invited_by_id", "expires_at", "revoked_at",
            "redeemed_at", "redeemed_by_id",
        ).first()
        if previous is None:
            return
        identity_fields = (
            "id", "created_at", "school_id", "household_id", "email",
            "token_digest", "invited_by_id", "expires_at",
        )
        if any(getattr(self, name) != previous[name] for name in identity_fields):
            raise ValidationError("Invitation identity cannot be changed.")
        if previous["revoked_at"] is not None and (
            self.revoked_at != previous["revoked_at"]
        ):
            raise ValidationError("An invitation cannot be unrevoked or revised.")
        if previous["redeemed_at"] is not None and (
            self.redeemed_at != previous["redeemed_at"]
            or self.redeemed_by_id != previous["redeemed_by_id"]
        ):
            raise ValidationError("A redeemed invitation cannot be changed.")
        if self.revoked_at is not None and self.redeemed_at is not None:
            raise ValidationError("Redeemed invitations cannot be revoked.")
        if (self.redeemed_at is None) != (self.redeemed_by_id is None):
            raise ValidationError("Redemption must identify the actor and time.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Invitations must be revoked, never deleted.")


class SchoolInvitationEvent(UUIDStampedModel):
    """Actor-attributed issue/revoke evidence for pending invitations."""

    ACTION_ISSUED = "ISSUED"
    ACTION_REVOKED = "REVOKED"
    ACTION_REDEEMED = "REDEEMED"

    school = models.ForeignKey(
        School, on_delete=models.PROTECT, related_name="invitation_events"
    )
    invitation = models.ForeignKey(
        HouseholdInvitation,
        on_delete=models.PROTECT,
        related_name="audit_events",
    )
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="jireh_invitation_events_performed",
    )
    action = models.CharField(
        max_length=16,
        choices=[
            (ACTION_ISSUED, "Issued"),
            (ACTION_REVOKED, "Revoked"),
            (ACTION_REDEEMED, "Redeemed"),
        ],
    )

    objects = ScopedQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["invitation", "action"],
                name="jireh_invite_event_unique_action",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "invitation"],
                name="jireh_invite_event_lookup",
            )
        ]

    def clean(self):
        super().clean()
        if self.school_id and self.invitation_id:
            if self.invitation.school_id != self.school_id:
                raise ValidationError("Invitation audit school mismatch.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Invitation audit events are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Invitation audit events cannot be deleted.")


class MailboxChallenge(UUIDStampedModel):
    """Single-use mailbox-control proof, independent of a household invitation.

    Its opaque token must be sent only to its designated mailbox by a
    separately verified trusted sender. This model is never itself a grant.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="jireh_mailbox_challenges",
    )
    email = models.EmailField(max_length=254)
    token_digest = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "email"],
                condition=Q(consumed_at__isnull=True),
                name="jireh_one_open_mailbox_proof",
            ),
        ]

    def clean(self):
        super().clean()
        if self.email and self.email != self.email.strip().casefold():
            raise ValidationError({"email": "Use a normalized email address."})
        if self._state.adding:
            return
        previous = type(self).objects.filter(pk=self.pk).values(
            "id", "created_at", "user_id", "email", "token_digest",
            "expires_at", "consumed_at",
        ).first()
        if previous is None:
            return
        immutable = ("id", "created_at", "user_id", "email", "token_digest", "expires_at")
        if any(getattr(self, name) != previous[name] for name in immutable):
            raise ValidationError("Mailbox challenge identity cannot change.")
        if previous["consumed_at"] is not None and (
            self.consumed_at != previous["consumed_at"]
        ):
            raise ValidationError("A used challenge cannot be modified.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Mailbox challenge records cannot be deleted.")


class RedemptionAttemptBudget(UUIDStampedModel):
    """Durable user-wide redemption throttle; no tokens or target IDs stored.

    One row per authenticated account, shared across sessions and schools.
    The caller locks the auth user before updating this row to serialize
    concurrent attempts on PostgreSQL. No public routing is enabled here.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="jireh_redemption_attempt_budget",
    )
    window_started_at = models.DateTimeField()
    attempt_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(attempt_count__lte=10),
                name="jireh_redemption_attempt_max10",
            ),
        ]


class LoginAttemptBudget(UUIDStampedModel):
    """Test-only durable authentication throttle, keyed by an HMAC digest.

    No username, password, client IP, user-agent or session ID is persisted.
    An index on identifier_digest and a database check enforce the budget.
    """

    identifier_digest = models.CharField(max_length=64, unique=True)
    window_started_at = models.DateTimeField()
    attempt_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(attempt_count__lte=10),
                name="jireh_login_attempt_max10",
            ),
        ]


class VerifiedRecoveryContact(UUIDStampedModel):
    """Account-bound mailbox proof; never trust User.email by itself."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="jireh_recovery_contacts",
    )
    proof = models.OneToOneField(
        MailboxChallenge, on_delete=models.PROTECT,
        related_name="recovery_contact",
    )
    email = models.EmailField(max_length=254)
    verified_at = models.DateTimeField()
    superseded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(superseded_at__isnull=True),
                name="jireh_one_current_recovery_contact",
            ),
        ]

    def clean(self):
        super().clean()
        if self.email and self.email != self.email.strip().casefold():
            raise ValidationError({"email": "Use a normalized mailbox."})
        if self.proof_id:
            if self.proof.user_id != self.user_id or self.proof.email != self.email:
                raise ValidationError("Recovery proof must match account and mailbox.")
            if self.proof.consumed_at is None:
                raise ValidationError("Recovery proof must be consumed before enrollment.")
        if not self._state.adding:
            previous = type(self).objects.filter(pk=self.pk).values(
                "user_id", "proof_id", "email", "verified_at",
                "superseded_at",
            ).first()
            if previous:
                if any(
                    getattr(self, field) != previous[field]
                    for field in ("user_id", "proof_id", "email", "verified_at")
                ):
                    raise ValidationError("Recovery contact identity is immutable.")
                if previous["superseded_at"] is not None and (
                    self.superseded_at != previous["superseded_at"]
                ):
                    raise ValidationError("Superseded recovery contacts are immutable.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Recovery contacts cannot be deleted.")


class RecoveryContactRotationEvent(UUIDStampedModel):
    """Actor-attributed immutable evidence of an old-to-new mailbox rotation."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="jireh_recovery_contact_rotations",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="jireh_recovery_rotations_performed",
    )
    old_contact = models.OneToOneField(
        VerifiedRecoveryContact, on_delete=models.PROTECT,
        related_name="rotation_out",
    )
    new_contact = models.OneToOneField(
        VerifiedRecoveryContact, on_delete=models.PROTECT,
        related_name="rotation_in",
    )

    def clean(self):
        super().clean()
        if self.old_contact_id and self.new_contact_id:
            if self.old_contact_id == self.new_contact_id:
                raise ValidationError("Rotation requires distinct contacts.")
            if (self.old_contact.user_id != self.user_id
                    or self.new_contact.user_id != self.user_id
                    or self.actor_id != self.user_id):
                raise ValidationError("Recovery rotation account mismatch.")
            if self.old_contact.superseded_at is None:
                raise ValidationError("Old recovery contact must be superseded.")
            if self.new_contact.superseded_at is not None:
                raise ValidationError("New recovery contact must be active.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Recovery rotation evidence is append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Recovery rotation evidence cannot be deleted.")


class PasswordRecoveryChallenge(UUIDStampedModel):
    """Opaque one-use recovery credential tied to a proven recovery contact."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="jireh_password_recovery_challenges",
    )
    contact = models.ForeignKey(
        VerifiedRecoveryContact, on_delete=models.PROTECT,
        related_name="recovery_challenges",
    )
    token_digest = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    password_changed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(consumed_at__isnull=True),
                name="jireh_one_open_recovery_challenge",
            )
        ]

    def clean(self):
        super().clean()
        if self.contact_id and self.contact.user_id != self.user_id:
            raise ValidationError("Recovery credential account mismatch.")
        if self.password_changed_at is not None and self.consumed_at is None:
            raise ValidationError("Completed recovery must consume its credential.")
        if not self._state.adding:
            previous = type(self).objects.filter(pk=self.pk).values(
                "user_id", "contact_id", "token_digest", "expires_at",
                "consumed_at", "password_changed_at",
            ).first()
            if previous:
                immutable = ("user_id", "contact_id", "token_digest", "expires_at")
                if any(getattr(self, field) != previous[field] for field in immutable):
                    raise ValidationError("Recovery credential identity is immutable.")
                if previous["consumed_at"] is not None and (
                    self.consumed_at != previous["consumed_at"]
                    or self.password_changed_at != previous["password_changed_at"]
                ):
                    raise ValidationError("Consumed recovery credential is immutable.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Recovery credentials cannot be deleted.")


class RecoveryAttemptBudget(UUIDStampedModel):
    """No raw account identifier or credential is saved in throttle rows."""

    PURPOSE_ISSUE = "ISSUE"
    PURPOSE_CONFIRM = "CONFIRM"

    identifier_digest = models.CharField(max_length=64)
    purpose = models.CharField(
        max_length=8,
        choices=[(PURPOSE_ISSUE, "Issue"), (PURPOSE_CONFIRM, "Confirm")],
    )
    window_started_at = models.DateTimeField()
    attempt_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["identifier_digest", "purpose"],
                name="jireh_recovery_budget_identity_purpose",
            ),
            models.CheckConstraint(
                condition=Q(attempt_count__lte=10),
                name="jireh_recovery_budget_max10",
            ),
        ]


class FirstDirectorBootstrapRequest(UUIDStampedModel):
    """Internal-only, two-operator first director approval record.

    Both operators must be separately allowlisted and authenticated by a
    trusted caller. No public routes or deployment settings enable this.
    A prior director grant at this school permanently disqualifies bootstrap.
    """

    school = models.ForeignKey(
        School, on_delete=models.PROTECT,
        related_name="first_director_bootstrap_requests",
    )
    subject = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="jireh_first_director_requests",
    )
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="jireh_first_director_proposals",
    )
    authorization_reference = models.CharField(max_length=120)
    expires_at = models.DateTimeField()
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="jireh_first_director_approvals",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    grant = models.OneToOneField(
        SchoolStaffAccess, on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="initial_director_approval",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school"],
                condition=Q(approved_at__isnull=True, closed_at__isnull=True),
                name="jireh_one_pending_initial_director",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        approved_at__isnull=True,
                        approved_by__isnull=True,
                        grant__isnull=True,
                    ) | Q(
                        approved_at__isnull=False,
                        approved_by__isnull=False,
                        grant__isnull=False,
                        closed_at__isnull=True,
                    )
                ),
                name="jireh_initial_director_state_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(approved_by__isnull=True)
                    | ~Q(proposed_by=F("approved_by"))
                ),
                name="jireh_initial_director_dual_control",
            ),
        ]

    def clean(self):
        super().clean()
        if not self._state.adding:
            before = type(self).objects.filter(pk=self.pk).values(
                "school_id", "subject_id", "proposed_by_id",
                "authorization_reference", "expires_at",
                "approved_by_id", "approved_at", "closed_at", "grant_id",
            ).first()
            if before:
                identity = (
                    "school_id", "subject_id", "proposed_by_id",
                    "authorization_reference", "expires_at",
                )
                if any(getattr(self, field) != before[field] for field in identity):
                    raise ValidationError("Initial director proposal identity is immutable.")
                if before["approved_at"] is not None or before["closed_at"] is not None:
                    state = ("approved_by_id", "approved_at", "closed_at", "grant_id")
                    if any(getattr(self, field) != before[field] for field in state):
                        raise ValidationError("Closed director approval is immutable.")

        if self.approved_by_id and self.approved_by_id == self.proposed_by_id:
            raise ValidationError("Distinct operators are required.")
        if self.grant_id and (
            self.grant.school_id != self.school_id
            or self.grant.user_id != self.subject_id
            or self.grant.role != SchoolStaffAccess.ROLE_AID_DIRECTOR
            or not self.grant.is_active
        ):
            raise ValidationError("Initial director approval grant binding invalid.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Initial director approvals cannot be deleted.")
