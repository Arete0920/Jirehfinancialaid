"""Immutable school setup preparation evidence; no runnable provisioning job."""

import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            CREATE FUNCTION jireh_setup_intent_immutable()
            RETURNS trigger AS $body$
            BEGIN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'School setup intent evidence is immutable';
            END;
            $body$ LANGUAGE plpgsql;
        """)
        cursor.execute(
            "CREATE TRIGGER jireh_setup_intent_protect_trigger "
            "BEFORE UPDATE OR DELETE ON schools_schoolsetupintent "
            "FOR EACH ROW EXECUTE FUNCTION jireh_setup_intent_immutable()"
        )


def remove(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DROP TRIGGER IF EXISTS jireh_setup_intent_protect_trigger "
            "ON schools_schoolsetupintent"
        )
        cursor.execute("DROP FUNCTION IF EXISTS jireh_setup_intent_immutable()")


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0022_operator_credential_recovery"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="SchoolSetupIntent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False,
                                       primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("idempotency_key", models.UUIDField(unique=True)),
                ("candidate_digest", models.CharField(max_length=64)),
                ("proposed_by", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_school_setup_intents",
                )),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=~models.Q(idempotency_key=uuid.UUID(int=0)),
                        name="jireh_setup_intent_key_nonzero",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(candidate_digest__regex=r"^[0-9a-f]{64}$"),
                        name="jireh_setup_intent_digest",
                    ),
                ],
            },
        ),
        migrations.RunPython(install, remove),
    ]
