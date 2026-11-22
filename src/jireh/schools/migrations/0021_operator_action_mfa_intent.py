"""Append-only operator WebAuthn action evidence; never an authorization grant."""

import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


GUARD_SQL = """
CREATE FUNCTION jireh_operator_action_intent_protect()
RETURNS trigger AS $body$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Operator action evidence cannot be deleted';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NOT EXISTS (
            SELECT 1 FROM schools_operatorwebauthnchallenge AS c
            WHERE c.id = NEW.challenge_id AND c.operator_id = NEW.operator_id
              AND c.expires_at = NEW.expires_at
              AND c.closed_at IS NULL AND c.verified_at IS NULL
        ) THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'Unbound or completed WebAuthn challenge';
        END IF;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF ROW(NEW.operator_id, NEW.challenge_id, NEW.action,
               NEW.payload_digest, NEW.expires_at, NEW.created_at)
           IS DISTINCT FROM
           ROW(OLD.operator_id, OLD.challenge_id, OLD.action,
               OLD.payload_digest, OLD.expires_at, OLD.created_at)
           OR OLD.consumed_at IS NOT NULL OR NEW.consumed_at IS NULL
           OR NEW.consumed_at > NEW.expires_at
           OR NOT EXISTS (
                SELECT 1 FROM schools_operatorwebauthnchallenge AS c
                WHERE c.id = NEW.challenge_id
                  AND c.operator_id = NEW.operator_id
                  AND c.verified_at IS NOT NULL
                  AND c.verified_at <= NEW.consumed_at
                  AND c.verified_at <= c.expires_at
           ) THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'Invalid operator action evidence transition';
        END IF;
    END IF;
    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(GUARD_SQL)
        cursor.execute(
            "CREATE TRIGGER jireh_operator_action_intent_protect_trigger "
            "BEFORE INSERT OR UPDATE OR DELETE "
            "ON schools_operatorwebauthnactionintent "
            "FOR EACH ROW EXECUTE FUNCTION "
            "jireh_operator_action_intent_protect()"
        )


def remove(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DROP TRIGGER IF EXISTS jireh_operator_action_intent_protect_trigger "
            "ON schools_operatorwebauthnactionintent"
        )
        cursor.execute(
            "DROP FUNCTION IF EXISTS jireh_operator_action_intent_protect()"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0020_operator_credential_activation_guard"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="OperatorWebAuthnActionIntent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False,
                                       primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("action", models.CharField(max_length=24, choices=[
                    ("DIRECTOR_PROPOSE", "Director proposal"),
                    ("DIRECTOR_APPROVE", "Director approval"),
                ])),
                ("payload_digest", models.CharField(max_length=64)),
                ("expires_at", models.DateTimeField()),
                ("consumed_at", models.DateTimeField(null=True, blank=True)),
                ("challenge", models.OneToOneField(
                    to="schools.operatorwebauthnchallenge",
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_privileged_action_intent",
                )),
                ("operator", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_operator_privileged_action_intents",
                )),
            ],
        ),
        migrations.RunPython(install, remove),
    ]
