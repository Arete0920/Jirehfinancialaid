"""PostgreSQL-only database-level tenant integrity; SQLite keeps model checks.

The invariant is preserved across raw/bulk writes by:
- row triggers verifying household/application/child/audit associations;
- immutable identity links for referenced application and selection records;
- immutable parent school ownership;
- append-only audit events (table owner/superuser can still bypass triggers).

This migration deliberately has NO Django schema-state changes. PostgreSQL
triggers are unregistered with Django models; do not claim portability or RLS.
The reverse migration drops only these explicitly named Jireh triggers/functions.
"""

from django.db import migrations


TENANT_FUNCTION = """
CREATE FUNCTION jireh_tenant_reference_guard() RETURNS trigger AS $body$
BEGIN
    IF TG_TABLE_NAME = 'schools_householdstudent' THEN
        IF TG_OP = 'UPDATE'
           AND (NEW.household_id, NEW.student_id)
               IS DISTINCT FROM (OLD.household_id, OLD.student_id) THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'Household/student identity cannot be reassigned';
        END IF;
        PERFORM 1
          FROM schools_household h
          JOIN schools_student s ON s.id = NEW.student_id
         WHERE h.id = NEW.household_id
           AND h.school_id = s.school_id;

    ELSIF TG_TABLE_NAME = 'financial_aid_aidapplication' THEN
        IF TG_OP = 'UPDATE'
           AND (NEW.school_id, NEW.academic_year_id, NEW.household_id)
               IS DISTINCT FROM (OLD.school_id, OLD.academic_year_id, OLD.household_id) THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'Application school, year, and household are immutable';
        END IF;
        PERFORM 1
          FROM schools_household h
          JOIN schools_academicyear y ON y.id = NEW.academic_year_id
         WHERE h.id = NEW.household_id
           AND h.school_id = NEW.school_id
           AND y.school_id = NEW.school_id;

    ELSIF TG_TABLE_NAME = 'financial_aid_aidapplicationstudent' THEN
        IF TG_OP = 'UPDATE'
           AND (NEW.application_id, NEW.household_student_id)
               IS DISTINCT FROM (OLD.application_id, OLD.household_student_id) THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'Application/student selection identity is immutable';
        END IF;
        PERFORM 1
          FROM financial_aid_aidapplication a
          JOIN schools_householdstudent hs ON hs.id = NEW.household_student_id
          JOIN schools_household h ON h.id = hs.household_id
          JOIN schools_student s ON s.id = hs.student_id
          JOIN schools_academicyear y ON y.id = a.academic_year_id
         WHERE a.id = NEW.application_id
           AND a.household_id = hs.household_id
           AND a.school_id = h.school_id
           AND a.school_id = s.school_id
           AND a.school_id = y.school_id;

    ELSIF TG_TABLE_NAME = 'financial_aid_aidauditevent' THEN
        IF TG_OP = 'DELETE' OR TG_OP = 'UPDATE' THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'Existing Jireh audit events cannot be modified or deleted';
        END IF;
        PERFORM 1
          FROM financial_aid_aidapplication a
          LEFT JOIN financial_aid_aidapplicationstudent sel
            ON sel.id = NEW.student_selection_id
         WHERE a.id = NEW.application_id
           AND a.school_id = NEW.school_id
           AND (
               (NEW.action = 'DRAFT_CREATED' AND NEW.student_selection_id IS NULL)
               OR
               (NEW.action = 'STUDENT_SELECTED'
                AND NEW.student_selection_id IS NOT NULL
                AND sel.application_id = a.id)
           );
    ELSE
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Unsupported Jireh tenant trigger table';
    END IF;

    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Jireh school/household relationship mismatch';
    END IF;
    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;
"""
SCHOOL_FUNCTION = """
CREATE FUNCTION jireh_freeze_school_binding() RETURNS trigger AS $body$
BEGIN
    IF NEW.school_id IS DISTINCT FROM OLD.school_id THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Jireh school ownership cannot be transferred in place';
    END IF;
    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;
"""

TRIGGER_SQL = (
    "CREATE TRIGGER jireh_tenant_link_guard "
    "BEFORE INSERT OR UPDATE ON schools_householdstudent "
    "FOR EACH ROW EXECUTE FUNCTION jireh_tenant_reference_guard()",
    "CREATE TRIGGER jireh_tenant_app_guard "
    "BEFORE INSERT OR UPDATE ON financial_aid_aidapplication "
    "FOR EACH ROW EXECUTE FUNCTION jireh_tenant_reference_guard()",
    "CREATE TRIGGER jireh_tenant_selection_guard "
    "BEFORE INSERT OR UPDATE ON financial_aid_aidapplicationstudent "
    "FOR EACH ROW EXECUTE FUNCTION jireh_tenant_reference_guard()",
    "CREATE TRIGGER jireh_tenant_audit_guard "
    "BEFORE INSERT OR UPDATE OR DELETE ON financial_aid_aidauditevent "
    "FOR EACH ROW EXECUTE FUNCTION jireh_tenant_reference_guard()",
    "CREATE TRIGGER jireh_school_guard "
    "BEFORE UPDATE OF school_id ON schools_household "
    "FOR EACH ROW EXECUTE FUNCTION jireh_freeze_school_binding()",
    "CREATE TRIGGER jireh_school_guard "
    "BEFORE UPDATE OF school_id ON schools_student "
    "FOR EACH ROW EXECUTE FUNCTION jireh_freeze_school_binding()",
    "CREATE TRIGGER jireh_school_guard "
    "BEFORE UPDATE OF school_id ON schools_academicyear "
    "FOR EACH ROW EXECUTE FUNCTION jireh_freeze_school_binding()",
)

DROP_SQL = (
    "DROP TRIGGER IF EXISTS jireh_school_guard ON schools_academicyear",
    "DROP TRIGGER IF EXISTS jireh_school_guard ON schools_student",
    "DROP TRIGGER IF EXISTS jireh_school_guard ON schools_household",
    "DROP TRIGGER IF EXISTS jireh_tenant_audit_guard ON financial_aid_aidauditevent",
    "DROP TRIGGER IF EXISTS jireh_tenant_selection_guard ON financial_aid_aidapplicationstudent",
    "DROP TRIGGER IF EXISTS jireh_tenant_app_guard ON financial_aid_aidapplication",
    "DROP TRIGGER IF EXISTS jireh_tenant_link_guard ON schools_householdstudent",
    "DROP FUNCTION IF EXISTS jireh_freeze_school_binding()",
    "DROP FUNCTION IF EXISTS jireh_tenant_reference_guard()",
)


def install_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(TENANT_FUNCTION)
        cursor.execute(SCHOOL_FUNCTION)
        for statement in TRIGGER_SQL:
            cursor.execute(statement)


def remove_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for statement in DROP_SQL:
            cursor.execute(statement)


class Migration(migrations.Migration):
    dependencies = [
        ("financial_aid", "0003_aidauditevent"),
        ("schools", "0003_schoolstaffaccess"),
    ]
    operations = [migrations.RunPython(install_triggers, remove_triggers)]
