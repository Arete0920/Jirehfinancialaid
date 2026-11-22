"""Verified-registration-only operator WebAuthn credential registry.

This does NOT provide an enrollment ceremony or authorization API. Only an
independently approved, verified ceremony can ever populate a real credential.
The trigger protects against ordinary SQL mutating enrollment identity,
replacing a key, lowering counters, unrevoking keys, or deleting history.
"""

import uuid

from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


GUARD_SQL = """
CREATE FUNCTION jireh_operator_webauthn_credential_protect()
RETURNS trigger AS $body$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Operator credential history cannot be deleted';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF ROW(NEW.operator_id, NEW.credential_id_digest, NEW.credential_data,
               NEW.rp_id, NEW.origin, NEW.created_at)
           IS DISTINCT FROM
           ROW(OLD.operator_id, OLD.credential_id_digest, OLD.credential_data,
               OLD.rp_id, OLD.origin, OLD.created_at) THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'Operator WebAuthn credential identity is immutable';
        END IF;
        IF (OLD.enrollment_verified_at IS NOT NULL AND
            NEW.enrollment_verified_at IS DISTINCT FROM OLD.enrollment_verified_at)
           OR (OLD.revoked_at IS NOT NULL AND
               NEW.revoked_at IS DISTINCT FROM OLD.revoked_at)
           OR NEW.sign_count < OLD.sign_count THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'Operator credential verification or counter cannot regress';
        END IF;
    END IF;
    IF NEW.sign_count > 4294967295
        OR (NEW.revoked_at IS NOT NULL AND
            NEW.enrollment_verified_at IS NOT NULL AND
            NEW.revoked_at < NEW.enrollment_verified_at) THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Invalid operator WebAuthn credential state';
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
            "CREATE TRIGGER jireh_operator_webauthn_credential_protect_trigger "
            "BEFORE INSERT OR UPDATE OR DELETE ON schools_operatorwebauthncredential "
            "FOR EACH ROW EXECUTE FUNCTION "
            "jireh_operator_webauthn_credential_protect()"
        )


def remove(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DROP TRIGGER IF EXISTS "
            "jireh_operator_webauthn_credential_protect_trigger "
            "ON schools_operatorwebauthncredential"
        )
        cursor.execute(
            "DROP FUNCTION IF EXISTS "
            "jireh_operator_webauthn_credential_protect()"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0015_operator_webauthn_challenge"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OperatorWebAuthnCredential",
            fields=[
                ("id", models.UUIDField(
                    default=uuid.uuid4, editable=False,
                    primary_key=True, serialize=False,
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("credential_id_digest", models.CharField(max_length=64, unique=True)),
                ("credential_data", models.BinaryField(max_length=4096)),
                ("rp_id", models.CharField(max_length=253)),
                ("origin", models.CharField(max_length=261)),
                ("enrollment_verified_at", models.DateTimeField(null=True, blank=True)),
                ("sign_count", models.PositiveBigIntegerField(default=0)),
                ("revoked_at", models.DateTimeField(null=True, blank=True)),
                ("operator", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_operator_webauthn_credentials",
                )),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=Q(sign_count__lte=4294967295),
                        name="jireh_operator_webauthn_counter32",
                    ),
                ],
            },
        ),
        migrations.RunPython(install, remove),
    ]
