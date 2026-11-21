"""PostgreSQL-only immutable access-grant bindings and no silent deletion.

Existing grant user, school/household, role, ID and creation date cannot
be changed in place. Revocation via is_active=False remains permitted.
This does NOT authorize granting or reactivating access; a separately
reviewed, actor-audited provisioning workflow is still needed.

The two trigger names deliberately do not match the earlier financial-aid
CI trigger-count pattern (jireh%guard). SQLite keeps model-level protections.
"""

from django.db import migrations


FUNCTION_SQL = """
CREATE FUNCTION jireh_grant_binding_protect() RETURNS trigger AS $body$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Jireh access grants cannot be deleted; revoke instead';
    END IF;

    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Jireh existing grant identity is immutable';
    END IF;

    IF TG_TABLE_NAME = 'schools_householdaccess' THEN
        IF NEW.user_id IS DISTINCT FROM OLD.user_id
           OR NEW.household_id IS DISTINCT FROM OLD.household_id THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'Jireh existing household grant binding is immutable';
        END IF;

    ELSIF TG_TABLE_NAME = 'schools_schoolstaffaccess' THEN
        IF NEW.user_id IS DISTINCT FROM OLD.user_id
           OR NEW.school_id IS DISTINCT FROM OLD.school_id
           OR NEW.role IS DISTINCT FROM OLD.role THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'Jireh existing staff grant binding is immutable';
        END IF;

    ELSE
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Unsupported access grant trigger table';
    END IF;

    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;
"""

CREATE_SQL = (
    "CREATE TRIGGER jireh_household_access_identity_protect "
    "BEFORE UPDATE OR DELETE ON schools_householdaccess "
    "FOR EACH ROW EXECUTE FUNCTION jireh_grant_binding_protect()",
    "CREATE TRIGGER jireh_school_staff_access_identity_protect "
    "BEFORE UPDATE OR DELETE ON schools_schoolstaffaccess "
    "FOR EACH ROW EXECUTE FUNCTION jireh_grant_binding_protect()",
)

DROP_SQL = (
    "DROP TRIGGER IF EXISTS jireh_school_staff_access_identity_protect "
    "ON schools_schoolstaffaccess",
    "DROP TRIGGER IF EXISTS jireh_household_access_identity_protect "
    "ON schools_householdaccess",
    "DROP FUNCTION IF EXISTS jireh_grant_binding_protect()",
)


def apply_grant_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(FUNCTION_SQL)
        for command in CREATE_SQL:
            cursor.execute(command)


def remove_grant_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for command in DROP_SQL:
            cursor.execute(command)


class Migration(migrations.Migration):
    dependencies = [("schools", "0003_schoolstaffaccess")]
    operations = [migrations.RunPython(apply_grant_guards, remove_grant_guards)]
