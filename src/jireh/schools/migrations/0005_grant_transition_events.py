"""PostgreSQL-only atomic record of grant creation and active-state changes.

The database role is evidence of the DB connection, not the real operator.
No historical event backfill; no public access or grant issuance is enabled.
The trigger and table writes roll back in the same transaction as the grant.
SQLite intentionally does not simulate this database guarantee.
"""

import uuid

from django.db import migrations, models
import django.db.models.deletion


CAPTURE_FUNCTION = """
CREATE FUNCTION jireh_capture_grant_transition() RETURNS trigger AS $body$
DECLARE
    v_school_id uuid;
    v_scope_id uuid;
    v_kind varchar(16);
    v_action varchar(16);
BEGIN
    IF TG_TABLE_NAME = 'schools_householdaccess' THEN
        SELECT school_id INTO v_school_id
          FROM schools_household WHERE id = NEW.household_id;
        v_scope_id := NEW.household_id;
        v_kind := 'HOUSEHOLD';
    ELSIF TG_TABLE_NAME = 'schools_schoolstaffaccess' THEN
        v_school_id := NEW.school_id;
        v_scope_id := NEW.school_id;
        v_kind := 'STAFF';
    ELSE
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Unsupported Jireh grant event source';
    END IF;
    IF v_school_id IS NULL THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Jireh grant school not found';
    END IF;
    IF TG_OP = 'INSERT' THEN
        v_action := 'CREATED';
    ELSIF NEW.is_active IS NOT DISTINCT FROM OLD.is_active THEN
        RETURN NEW;
    ELSIF NEW.is_active THEN
        v_action := 'REACTIVATED';
    ELSE
        v_action := 'REVOKED';
    END IF;

    INSERT INTO schools_granttransitionevent (
        id, created_at, updated_at, school_id, grant_kind,
        grant_id, scope_id, subject_user_id, action, is_active, database_role
    ) VALUES (
        gen_random_uuid(), clock_timestamp(), clock_timestamp(),
        v_school_id, v_kind, NEW.id, v_scope_id, NEW.user_id::text,
        v_action, NEW.is_active, CURRENT_USER
    );
    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;
"""
PROTECT_FUNCTION = """
CREATE FUNCTION jireh_protect_grant_transition_event() RETURNS trigger AS $body$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514',
        MESSAGE = 'Jireh grant event rows cannot be updated or deleted';
END;
$body$ LANGUAGE plpgsql;
"""

CREATE_TRIGGERS = (
    "CREATE TRIGGER jireh_household_grant_transition_capture "
    "AFTER INSERT OR UPDATE OF is_active ON schools_householdaccess "
    "FOR EACH ROW EXECUTE FUNCTION jireh_capture_grant_transition()",
    "CREATE TRIGGER jireh_staff_grant_transition_capture "
    "AFTER INSERT OR UPDATE OF is_active ON schools_schoolstaffaccess "
    "FOR EACH ROW EXECUTE FUNCTION jireh_capture_grant_transition()",
    "CREATE TRIGGER jireh_grant_transition_append_only "
    "BEFORE UPDATE OR DELETE ON schools_granttransitionevent "
    "FOR EACH ROW EXECUTE FUNCTION jireh_protect_grant_transition_event()",
)

DROP_TRIGGERS = (
    "DROP TRIGGER IF EXISTS jireh_grant_transition_append_only "
    "ON schools_granttransitionevent",
    "DROP TRIGGER IF EXISTS jireh_staff_grant_transition_capture "
    "ON schools_schoolstaffaccess",
    "DROP TRIGGER IF EXISTS jireh_household_grant_transition_capture "
    "ON schools_householdaccess",
    "DROP FUNCTION IF EXISTS jireh_protect_grant_transition_event()",
    "DROP FUNCTION IF EXISTS jireh_capture_grant_transition()",
)


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(CAPTURE_FUNCTION)
        cursor.execute(PROTECT_FUNCTION)
        for statement in CREATE_TRIGGERS:
            cursor.execute(statement)


def remove(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for statement in DROP_TRIGGERS:
            cursor.execute(statement)


class Migration(migrations.Migration):
    dependencies = [("schools", "0004_pg_grant_guards")]

    operations = [
        migrations.CreateModel(
            name="GrantTransitionEvent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False,
                        primary_key=True, serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "grant_kind",
                    models.CharField(
                        max_length=16,
                        choices=[
                            ("HOUSEHOLD", "Household"), ("STAFF", "Staff")
                        ],
                    ),
                ),
                ("grant_id", models.UUIDField()),
                ("scope_id", models.UUIDField()),
                ("subject_user_id", models.CharField(max_length=128)),
                (
                    "action",
                    models.CharField(
                        max_length=16,
                        choices=[
                            ("CREATED", "Created"),
                            ("REVOKED", "Revoked"),
                            ("REACTIVATED", "Reactivated"),
                        ],
                    ),
                ),
                ("is_active", models.BooleanField()),
                ("database_role", models.CharField(max_length=128)),
                (
                    "school",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="grant_transition_events",
                        to="schools.school",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["school", "grant_id"],
                        name="jireh_grant_event_lookup",
                    )
                ]
            },
        ),
        migrations.RunPython(install, remove),
    ]
