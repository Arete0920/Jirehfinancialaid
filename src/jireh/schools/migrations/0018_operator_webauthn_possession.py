"""Pending WebAuthn key possession evidence; internal-only and disabled."""

import uuid

from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


GUARD_SQL = """
CREATE FUNCTION jireh_operator_possession_protect() RETURNS trigger AS $body$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Operator possession evidence cannot be deleted';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF ROW(NEW.operator_id, NEW.credential_id, NEW.challenge,
               NEW.expires_at, NEW.created_at)
          IS DISTINCT FROM
           ROW(OLD.operator_id, OLD.credential_id, OLD.challenge,
               OLD.expires_at, OLD.created_at)
           OR OLD.closed_at IS NOT NULL
           OR NEW.closed_at IS NULL
           OR (NEW.verified_at IS NOT NULL
               AND (NEW.verified_at IS DISTINCT FROM NEW.closed_at
               OR NEW.verified_at > NEW.expires_at
               OR NEW.verified_sign_count IS NULL))
           OR (NEW.verified_at IS NULL AND NEW.verified_sign_count IS NOT NULL)
           THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'Invalid operator possession state transition';
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
            "CREATE TRIGGER jireh_operator_possession_protect_trigger "
            "BEFORE UPDATE OR DELETE ON schools_operatorwebauthnpossessionchallenge "
            "FOR EACH ROW EXECUTE FUNCTION jireh_operator_possession_protect()"
        )


def remove(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DROP TRIGGER IF EXISTS jireh_operator_possession_protect_trigger "
            "ON schools_operatorwebauthnpossessionchallenge"
        )
        cursor.execute("DROP FUNCTION IF EXISTS jireh_operator_possession_protect()")


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0017_operator_webauthn_registration"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OperatorWebAuthnPossessionChallenge",
            fields=[
                ("id", models.UUIDField(
                    default=uuid.uuid4, editable=False,
                    primary_key=True, serialize=False,
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("challenge", models.CharField(max_length=128, unique=True)),
                ("expires_at", models.DateTimeField()),
                ("closed_at", models.DateTimeField(null=True, blank=True)),
                ("verified_at", models.DateTimeField(null=True, blank=True)),
                ("verified_sign_count", models.PositiveBigIntegerField(
                    null=True, blank=True,
                )),
                ("credential", models.ForeignKey(
                    to="schools.operatorwebauthncredential",
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_possession_proofs",
                )),
                ("operator", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_operator_possession_proofs",
                )),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=["operator"], condition=Q(closed_at__isnull=True),
                        name="jireh_one_open_possession_proof",
                    ),
                    models.CheckConstraint(
                        condition=(
                            Q(verified_at__isnull=True, verified_sign_count__isnull=True)
                            | Q(verified_at__isnull=False, closed_at__isnull=False,
                                verified_sign_count__isnull=False)
                        ),
                        name="jireh_possession_proof_verified_closed",
                    ),
                    models.CheckConstraint(
                        condition=Q(verified_sign_count__isnull=True)
                        | Q(verified_sign_count__lte=4294967295),
                        name="jireh_possession_proof_counter32",
                    ),
                ],
            },
        ),
        migrations.RunPython(install, remove),
    ]
