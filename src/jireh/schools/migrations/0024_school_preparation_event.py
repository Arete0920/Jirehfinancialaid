"""Durable, immutable pre-activation preparation-job evidence."""

import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            CREATE FUNCTION jireh_school_preparation_immutable()
            RETURNS trigger AS $body$
            BEGIN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'School preparation evidence is immutable';
            END;
            $body$ LANGUAGE plpgsql;
        """)
        cursor.execute(
            "CREATE TRIGGER jireh_school_preparation_protect "
            "BEFORE UPDATE OR DELETE ON schools_schoolpreparationevent "
            "FOR EACH ROW EXECUTE FUNCTION jireh_school_preparation_immutable()"
        )


def remove(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DROP TRIGGER IF EXISTS jireh_school_preparation_protect "
            "ON schools_schoolpreparationevent"
        )
        cursor.execute("DROP FUNCTION IF EXISTS jireh_school_preparation_immutable()")


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0023_school_setup_intent"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="SchoolPreparationEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False,
                                       primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("request_key", models.UUIDField()),
                ("sequence", models.PositiveSmallIntegerField()),
                ("attempt", models.PositiveSmallIntegerField()),
                ("action", models.CharField(
                    max_length=16,
                    choices=[
                        ("QUEUED", "Queued"), ("STARTED", "Started"),
                        ("PREPARED", "Prepared"), ("FAILED", "Failed"),
                        ("REQUEUED", "Requeued"),
                    ],
                )),
                ("reason", models.CharField(blank=True, default="", max_length=32)),
                ("intent", models.ForeignKey(
                    to="schools.schoolsetupintent",
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="preparation_events",
                )),
                ("actor", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_school_preparation_events",
                )),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=["intent", "sequence"], name="jireh_prep_event_sequence",
                    ),
                    models.UniqueConstraint(
                        fields=["intent", "request_key", "action"],
                        name="jireh_prep_event_request_action",
                    ),
                    models.CheckConstraint(
                        condition=~models.Q(request_key=uuid.UUID(int=0)),
                        name="jireh_prep_event_nonzero_key",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(sequence__gte=1, sequence__lte=9,
                                           attempt__gte=1, attempt__lte=3),
                        name="jireh_prep_event_bounds",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(action__in=["QUEUED", "STARTED", "PREPARED"], reason="")
                            | models.Q(action="FAILED", reason="SCHOOL_CODE_CONFLICT")
                            | models.Q(action="REQUEUED", reason="CODE_CONFLICT_RECHECK")
                        ),
                        name="jireh_prep_event_reason",
                    ),
                ],
            },
        ),
        migrations.RunPython(install, remove),
    ]
