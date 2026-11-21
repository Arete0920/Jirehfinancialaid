"""Actor-attributed school revocation records; append-only under PostgreSQL.

This is separate from database-role-only grant transition history. It does
not enable grant issuance, identity verification or public access endpoints.
"""

import uuid

from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


CREATE_FUNCTION = """
CREATE FUNCTION jireh_protect_school_grant_decision() RETURNS trigger AS $body$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514',
        MESSAGE = 'Jireh operator grant decisions cannot be changed or deleted';
END;
$body$ LANGUAGE plpgsql;
"""

CREATE_TRIGGER = (
    "CREATE TRIGGER jireh_school_grant_decision_append_only "
    "BEFORE UPDATE OR DELETE ON schools_schoolgrantdecisionevent "
    "FOR EACH ROW EXECUTE FUNCTION jireh_protect_school_grant_decision()"
)


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(CREATE_FUNCTION)
        cursor.execute(CREATE_TRIGGER)


def remove(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DROP TRIGGER IF EXISTS jireh_school_grant_decision_append_only "
            "ON schools_schoolgrantdecisionevent"
        )
        cursor.execute(
            "DROP FUNCTION IF EXISTS jireh_protect_school_grant_decision()"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0005_grant_transition_events"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SchoolGrantDecisionEvent",
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
                        choices=[("HOUSEHOLD", "Household"), ("STAFF", "Staff")],
                        max_length=16,
                    ),
                ),
                ("grant_id", models.UUIDField()),
                ("scope_id", models.UUIDField()),
                (
                    "action",
                    models.CharField(
                        choices=[("REVOKED", "Revoked")], max_length=16,
                    ),
                ),
                (
                    "school",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="grant_decisions", to="schools.school",
                    ),
                ),
                (
                    "actor_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="jireh_grant_decisions_performed",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "target_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="jireh_grant_decisions_received",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=Q(grant_kind__in=["HOUSEHOLD", "STAFF"]),
                        name="jireh_operator_valid_kind",
                    ),
                    models.CheckConstraint(
                        condition=Q(action="REVOKED"),
                        name="jireh_operator_revoke_only",
                    ),
                ],
                "indexes": [
                    models.Index(
                        fields=["school", "grant_id"],
                        name="jireh_operator_grant_lookup",
                    )
                ],
            },
        ),
        migrations.RunPython(install, remove),
    ]
