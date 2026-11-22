"""Persist internal-only single-use operator WebAuthn challenge evidence.

No public endpoints or operator activation. PostgreSQL blocks raw SQL changes
to immutable challenge identity, reopening a closed row, and deletion.
"""

import uuid

from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


PROTECT_SQL = """
CREATE FUNCTION jireh_operator_webauthn_challenge_protect()
RETURNS trigger AS $body$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Operator WebAuthn challenge history cannot be deleted';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF ROW(NEW.operator_id, NEW.rp_id, NEW.origin,
               NEW.credential_id_digest, NEW.challenge,
               NEW.expires_at, NEW.created_at)
          IS DISTINCT FROM
           ROW(OLD.operator_id, OLD.rp_id, OLD.origin,
               OLD.credential_id_digest, OLD.challenge,
               OLD.expires_at, OLD.created_at)
           OR OLD.closed_at IS NOT NULL THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'Operator WebAuthn challenge identity is immutable';
        END IF;
        IF NEW.closed_at IS NULL
           OR (NEW.verified_at IS NOT NULL
               AND NEW.verified_at IS DISTINCT FROM NEW.closed_at)
           OR (NEW.verified_at IS NOT NULL
               AND NEW.verified_at > NEW.expires_at) THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'Invalid operator WebAuthn challenge transition';
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
        cursor.execute(PROTECT_SQL)
        cursor.execute(
            "CREATE TRIGGER jireh_operator_webauthn_challenge_protect_trigger "
            "BEFORE UPDATE OR DELETE ON schools_operatorwebauthnchallenge "
            "FOR EACH ROW EXECUTE FUNCTION "
            "jireh_operator_webauthn_challenge_protect()"
        )


def remove(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DROP TRIGGER IF EXISTS "
            "jireh_operator_webauthn_challenge_protect_trigger "
            "ON schools_operatorwebauthnchallenge"
        )
        cursor.execute(
            "DROP FUNCTION IF EXISTS "
            "jireh_operator_webauthn_challenge_protect()"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0014_first_director_bootstrap"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OperatorWebAuthnChallenge",
            fields=[
                ("id", models.UUIDField(
                    default=uuid.uuid4, editable=False,
                    primary_key=True, serialize=False,
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("rp_id", models.CharField(max_length=253)),
                ("origin", models.CharField(max_length=261)),
                ("credential_id_digest", models.CharField(max_length=64)),
                ("challenge", models.CharField(max_length=128, unique=True)),
                ("expires_at", models.DateTimeField()),
                ("closed_at", models.DateTimeField(null=True, blank=True)),
                ("verified_at", models.DateTimeField(null=True, blank=True)),
                ("operator", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_operator_webauthn_challenges",
                )),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=["operator"],
                        condition=Q(closed_at__isnull=True),
                        name="jireh_one_open_webauthn_operator",
                    ),
                    models.CheckConstraint(
                        condition=(
                            Q(verified_at__isnull=True)
                            | Q(closed_at__isnull=False)
                        ),
                        name="jireh_webauthn_verified_closed",
                    ),
                ],
            },
        ),
        migrations.RunPython(install, remove),
    ]
