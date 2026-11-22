"""Auditable owner/integration-manager WebAuthn enrollment approvals."""

import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


GUARD_SQL = """
CREATE FUNCTION jireh_operator_enrollment_approval_protect()
RETURNS trigger AS $body$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Operator enrollment approval evidence is immutable';
    END IF;
    IF NEW.operator_id = NEW.approver_id THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Operator cannot approve own credential';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM schools_operatorwebauthncredential AS c
        JOIN schools_operatorwebauthnregistration AS r
          ON r.id = NEW.registration_id
        JOIN schools_operatorwebauthnpossessionchallenge AS p
          ON p.id = NEW.possession_proof_id
        WHERE c.id = NEW.credential_id AND c.operator_id = NEW.operator_id
          AND c.enrollment_verified_at IS NULL AND c.revoked_at IS NULL
          AND r.operator_id = NEW.operator_id
          AND r.credential_id_digest = c.credential_id_digest
          AND r.closed_at IS NOT NULL
          AND p.operator_id = NEW.operator_id AND p.credential_id = c.id
          AND p.verified_at IS NOT NULL
          AND p.verified_sign_count IS NOT NULL
          AND p.verified_at <= NEW.approved_at
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Missing eligible credential registration or possession';
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
            "CREATE TRIGGER jireh_operator_enrollment_approval_guard "
            "BEFORE INSERT OR UPDATE OR DELETE ON "
            "schools_operatorwebauthnenrollmentapproval "
            "FOR EACH ROW EXECUTE FUNCTION "
            "jireh_operator_enrollment_approval_protect()"
        )


def remove(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DROP TRIGGER IF EXISTS jireh_operator_enrollment_approval_guard "
            "ON schools_operatorwebauthnenrollmentapproval"
        )
        cursor.execute(
            "DROP FUNCTION IF EXISTS jireh_operator_enrollment_approval_protect()"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0018_operator_webauthn_possession"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="OperatorWebAuthnEnrollmentApproval",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4,
                                       editable=False, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("approver_role", models.CharField(max_length=20, choices=[
                    ("OWNER", "Owner"),
                    ("INTEGRATION_MANAGER", "Integration manager"),
                ])),
                ("identity_verification_reference", models.CharField(max_length=120)),
                ("approved_at", models.DateTimeField()),
                ("approver", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_operator_enrollment_approvals")),
                ("operator", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_approved_enrollments")),
                ("credential", models.OneToOneField(
                    to="schools.operatorwebauthncredential",
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_enrollment_approval")),
                ("registration", models.ForeignKey(
                    to="schools.operatorwebauthnregistration",
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_enrollment_approvals")),
                ("possession_proof", models.OneToOneField(
                    to="schools.operatorwebauthnpossessionchallenge",
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_enrollment_approval")),
            ],
        ),
        migrations.RunPython(install, remove),
    ]
