"""Immutable WebAuthn loss/recovery evidence, with PostgreSQL tamper guards."""

import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


GUARD_SQL = """
CREATE FUNCTION jireh_operator_recovery_guard() RETURNS trigger AS $body$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Operator recovery history cannot change';
    END IF;
    IF NEW.authorized_by_id = NEW.operator_id
        OR NOT EXISTS (
            SELECT 1 FROM schools_operatorwebauthncredential c
            WHERE c.id = NEW.credential_id
              AND c.operator_id = NEW.operator_id
              AND c.revoked_at = NEW.authorized_at
              AND c.enrollment_verified_at IS NOT NULL
              AND c.enrollment_verified_at <= NEW.authorized_at
        ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Independent recovery must revoke its enrolled key';
    END IF;
    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;

CREATE FUNCTION jireh_operator_replacement_guard() RETURNS trigger AS $body$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Operator replacement history cannot change';
    END IF;
    IF NEW.confirmed_by_id = NEW.operator_id
        OR NOT EXISTS (
            SELECT 1 FROM schools_operatorwebauthnrecovery r
            JOIN schools_operatorwebauthncredential old
              ON old.id = r.credential_id
            JOIN schools_operatorwebauthncredential fresh
              ON fresh.id = NEW.replacement_credential_id
            JOIN schools_operatorwebauthnenrollmentapproval a
              ON a.credential_id = fresh.id
            WHERE r.id = NEW.recovery_id
              AND r.operator_id = NEW.operator_id
              AND old.revoked_at = r.authorized_at
              AND fresh.id <> old.id
              AND fresh.operator_id = r.operator_id
              AND fresh.rp_id = old.rp_id AND fresh.origin = old.origin
              AND fresh.created_at > r.authorized_at
              AND fresh.enrollment_verified_at IS NOT NULL
              AND fresh.enrollment_verified_at > r.authorized_at
              AND fresh.enrollment_verified_at <= NEW.confirmed_at
              AND fresh.revoked_at IS NULL
              AND a.operator_id = r.operator_id
              AND a.approved_at = fresh.enrollment_verified_at
              AND a.approver_id <> r.operator_id
        ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Replacement requires a distinct newly approved key';
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
            "CREATE TRIGGER jireh_operator_recovery_protect_trigger "
            "BEFORE INSERT OR UPDATE OR DELETE ON schools_operatorwebauthnrecovery "
            "FOR EACH ROW EXECUTE FUNCTION jireh_operator_recovery_guard()"
        )
        cursor.execute(
            "CREATE TRIGGER jireh_operator_replacement_protect_trigger "
            "BEFORE INSERT OR UPDATE OR DELETE "
            "ON schools_operatorwebauthnrecoveryreplacement "
            "FOR EACH ROW EXECUTE FUNCTION jireh_operator_replacement_guard()"
        )


def remove(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DROP TRIGGER IF EXISTS jireh_operator_replacement_protect_trigger "
            "ON schools_operatorwebauthnrecoveryreplacement"
        )
        cursor.execute(
            "DROP TRIGGER IF EXISTS jireh_operator_recovery_protect_trigger "
            "ON schools_operatorwebauthnrecovery"
        )
        cursor.execute("DROP FUNCTION IF EXISTS jireh_operator_replacement_guard()")
        cursor.execute("DROP FUNCTION IF EXISTS jireh_operator_recovery_guard()")


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0021_operator_action_mfa_intent"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OperatorWebAuthnRecovery",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4,
                                       editable=False, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("approver_role", models.CharField(max_length=20, choices=[
                    ("OWNER", "Owner"),
                    ("INTEGRATION_MANAGER", "Integration manager"),
                ])),
                ("reason", models.CharField(max_length=12, choices=[
                    ("LOST", "Lost credential"),
                    ("COMPROMISED", "Compromised credential"),
                ])),
                ("identity_verification_reference", models.CharField(max_length=120)),
                ("authorized_at", models.DateTimeField()),
                ("credential", models.OneToOneField(
                    to="schools.operatorwebauthncredential",
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_recovery")),
                ("operator", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_operator_recoveries")),
                ("authorized_by", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_authorized_operator_recoveries")),
            ],
        ),
        migrations.CreateModel(
            name="OperatorWebAuthnRecoveryReplacement",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4,
                                       editable=False, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("approver_role", models.CharField(max_length=20, choices=[
                    ("OWNER", "Owner"),
                    ("INTEGRATION_MANAGER", "Integration manager"),
                ])),
                ("confirmation_reference", models.CharField(max_length=120)),
                ("confirmed_at", models.DateTimeField()),
                ("recovery", models.OneToOneField(
                    to="schools.operatorwebauthnrecovery",
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_replacement")),
                ("replacement_credential", models.OneToOneField(
                    to="schools.operatorwebauthncredential",
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_recovery_replacement")),
                ("operator", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_operator_recovery_replacements")),
                ("confirmed_by", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_confirmed_recovery_replacements")),
            ],
        ),
        migrations.RunPython(install, remove),
    ]
