"""Internal-only WebAuthn registration journal. No live operator activation."""

import uuid

from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


GUARD_SQL = """
CREATE FUNCTION jireh_operator_registration_protect() RETURNS trigger AS $body$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Operator registration history cannot be deleted';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF ROW(NEW.operator_id, NEW.rp_id, NEW.origin,
               NEW.challenge, NEW.expires_at, NEW.created_at)
           IS DISTINCT FROM
           ROW(OLD.operator_id, OLD.rp_id, OLD.origin,
               OLD.challenge, OLD.expires_at, OLD.created_at)
           OR OLD.closed_at IS NOT NULL
           OR NEW.closed_at IS NULL
           OR (NEW.credential_id_digest IS NOT NULL
               AND NEW.closed_at > NEW.expires_at) THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'Invalid operator registration transition';
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
            "CREATE TRIGGER jireh_operator_registration_protect_trigger "
            "BEFORE UPDATE OR DELETE ON schools_operatorwebauthnregistration "
            "FOR EACH ROW EXECUTE FUNCTION jireh_operator_registration_protect()"
        )


def remove(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DROP TRIGGER IF EXISTS jireh_operator_registration_protect_trigger "
            "ON schools_operatorwebauthnregistration"
        )
        cursor.execute("DROP FUNCTION IF EXISTS jireh_operator_registration_protect()")


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0016_operator_webauthn_credential"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OperatorWebAuthnRegistration",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False,
                                       primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("rp_id", models.CharField(max_length=253)),
                ("origin", models.CharField(max_length=261)),
                ("challenge", models.CharField(max_length=128, unique=True)),
                ("expires_at", models.DateTimeField()),
                ("closed_at", models.DateTimeField(null=True, blank=True)),
                ("credential_id_digest", models.CharField(
                    max_length=64, null=True, blank=True)),
                ("operator", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_operator_webauthn_registrations",
                )),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=["operator"],
                        condition=Q(closed_at__isnull=True),
                        name="jireh_one_open_operator_registration",
                    ),
                    models.CheckConstraint(
                        condition=(Q(credential_id_digest__isnull=True) |
                                   Q(closed_at__isnull=False)),
                        name="jireh_operator_registration_closed",
                    ),
                ],
            },
        ),
        migrations.RunPython(install, remove),
    ]
