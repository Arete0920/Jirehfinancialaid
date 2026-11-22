"""Reject direct WebAuthn credential activation without a recorded approval.

The original immutable-credential trigger protects against *reversal* of an
approved enrollment, but not forged NULL -> timestamp activation. Keep that
trigger intact; this additional PostgreSQL-only guard checks the approval
record before any initial activation. No data is changed by this migration.
"""

from django.db import migrations


SQL = """
CREATE FUNCTION jireh_web_authn_activation_evidence_protect()
RETURNS trigger AS $body$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.enrollment_verified_at IS NOT NULL THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'Operator credential must be registered pending';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.enrollment_verified_at IS NULL
       AND NEW.enrollment_verified_at IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM schools_operatorwebauthnenrollmentapproval AS a
            WHERE a.credential_id = NEW.id
              AND a.operator_id = NEW.operator_id
              AND a.approved_at = NEW.enrollment_verified_at
              AND a.approver_id <> NEW.operator_id
              AND a.approver_role IN ('OWNER', 'INTEGRATION_MANAGER')
        ) THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'Operator activation requires independent approval evidence';
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
        cursor.execute(SQL)
        cursor.execute(
            "CREATE TRIGGER jireh_operator_activation_evidence_protect_trigger "
            "BEFORE INSERT OR UPDATE OF enrollment_verified_at "
            "ON schools_operatorwebauthncredential "
            "FOR EACH ROW EXECUTE FUNCTION "
            "jireh_web_authn_activation_evidence_protect()"
        )


def remove(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DROP TRIGGER IF EXISTS "
            "jireh_operator_activation_evidence_protect_trigger "
            "ON schools_operatorwebauthncredential"
        )
        cursor.execute(
            "DROP FUNCTION IF EXISTS "
            "jireh_web_authn_activation_evidence_protect()"
        )


class Migration(migrations.Migration):
    dependencies = [("schools", "0019_operator_webauthn_enrollment_approval")]

    operations = [migrations.RunPython(install, remove)]
