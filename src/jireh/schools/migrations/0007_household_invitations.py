"""Pending household invitations, with PostgreSQL identity and audit guards.

A pending invitation is not a household access grant. This migration does not
install endpoints, send email, redeem secrets or provision accounts.
"""

import uuid

from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


GUARD_INVITATION = """
CREATE FUNCTION jireh_guard_household_invitation() RETURNS trigger AS $body$
DECLARE
    v_school_id uuid;
BEGIN
    SELECT school_id INTO v_school_id
      FROM schools_household WHERE id = NEW.household_id;
    IF v_school_id IS DISTINCT FROM NEW.school_id THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='Jireh invitation household school mismatch';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF ROW(
            NEW.id, NEW.created_at, NEW.school_id, NEW.household_id,
            NEW.email, NEW.token_digest, NEW.invited_by_id, NEW.expires_at
        ) IS DISTINCT FROM ROW(
            OLD.id, OLD.created_at, OLD.school_id, OLD.household_id,
            OLD.email, OLD.token_digest, OLD.invited_by_id, OLD.expires_at
        ) THEN
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='Jireh invitation identity is immutable';
        END IF;
        IF OLD.revoked_at IS NOT NULL AND
           NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='Jireh revoked invitation cannot be changed';
        END IF;
    END IF;
    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;
"""

GUARD_EVENT = """
CREATE FUNCTION jireh_guard_invitation_event() RETURNS trigger AS $body$
DECLARE
    v_school_id uuid;
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT school_id INTO v_school_id
          FROM schools_householdinvitation WHERE id = NEW.invitation_id;
        IF v_school_id IS DISTINCT FROM NEW.school_id THEN
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='Jireh invitation audit school mismatch';
        END IF;
        RETURN NEW;
    END IF;
    RAISE EXCEPTION USING ERRCODE='23514',
        MESSAGE='Jireh invitation event records are append-only';
END;
$body$ LANGUAGE plpgsql;
"""

REJECT_DELETE = """
CREATE FUNCTION jireh_reject_household_invitation_delete() RETURNS trigger AS $body$
BEGIN
    RAISE EXCEPTION USING ERRCODE='23514',
        MESSAGE='Jireh invitations must be revoked instead of deleted';
END;
$body$ LANGUAGE plpgsql;
"""

CREATE_TRIGGERS = (
    "CREATE TRIGGER jireh_invitation_identity_protect "
    "BEFORE INSERT OR UPDATE ON schools_householdinvitation "
    "FOR EACH ROW EXECUTE FUNCTION jireh_guard_household_invitation()",
    "CREATE TRIGGER jireh_invitation_delete_protect "
    "BEFORE DELETE ON schools_householdinvitation "
    "FOR EACH ROW EXECUTE FUNCTION jireh_reject_household_invitation_delete()",
    "CREATE TRIGGER jireh_invitation_event_protect "
    "BEFORE INSERT OR UPDATE OR DELETE ON schools_schoolinvitationevent "
    "FOR EACH ROW EXECUTE FUNCTION jireh_guard_invitation_event()",
)

DROP_TRIGGERS = (
    "DROP TRIGGER IF EXISTS jireh_invitation_event_protect "
    "ON schools_schoolinvitationevent",
    "DROP TRIGGER IF EXISTS jireh_invitation_delete_protect "
    "ON schools_householdinvitation",
    "DROP TRIGGER IF EXISTS jireh_invitation_identity_protect "
    "ON schools_householdinvitation",
    "DROP FUNCTION IF EXISTS jireh_guard_invitation_event()",
    "DROP FUNCTION IF EXISTS jireh_reject_household_invitation_delete()",
    "DROP FUNCTION IF EXISTS jireh_guard_household_invitation()",
)


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for definition in (
            GUARD_INVITATION, GUARD_EVENT, REJECT_DELETE,
        ):
            cursor.execute(definition)
        for statement in CREATE_TRIGGERS:
            cursor.execute(statement)


def remove(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for statement in DROP_TRIGGERS:
            cursor.execute(statement)


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0006_school_grant_decision_events"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="HouseholdInvitation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False,
                                        primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("email", models.EmailField(max_length=254)),
                ("token_digest", models.CharField(max_length=64, unique=True)),
                ("expires_at", models.DateTimeField()),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("school", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="household_invitations", to="schools.school",
                )),
                ("household", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="invitations", to="schools.household",
                )),
                ("invited_by", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_household_invitations_issued",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=["household", "email"],
                        condition=Q(revoked_at__isnull=True),
                        name="jireh_open_household_invite",
                    ),
                ],
                "indexes": [
                    models.Index(
                        fields=["school", "household"],
                        name="jireh_invite_school_house",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="SchoolInvitationEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False,
                                        primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("action", models.CharField(
                    choices=[("ISSUED", "Issued"), ("REVOKED", "Revoked")],
                    max_length=16,
                )),
                ("school", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="invitation_events", to="schools.school",
                )),
                ("invitation", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="audit_events", to="schools.householdinvitation",
                )),
                ("actor_user", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_invitation_events_performed",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=["invitation", "action"],
                        name="jireh_invite_event_unique_action",
                    ),
                ],
                "indexes": [
                    models.Index(
                        fields=["school", "invitation"],
                        name="jireh_invite_event_lookup",
                    ),
                ],
            },
        ),
        migrations.RunPython(install, remove),
    ]
