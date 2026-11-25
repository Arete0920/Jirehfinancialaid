"""Protect director credential and assertion history on PostgreSQL.

Structural integrity only; a trusted writer still verifies signatures. No live
credential enrollment, database grant, or production authorization is added.
"""
from django.db import migrations


CREDENTIAL_SQL = """
CREATE FUNCTION jireh_director_credential_history() RETURNS trigger AS $body$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Director credential history is immutable';
    END IF;
    IF ROW(NEW.id, NEW.created_at, NEW.grant_id, NEW.credential_id_digest,
           NEW.credential_data, NEW.rp_id)
       IS DISTINCT FROM ROW(OLD.id, OLD.created_at, OLD.grant_id, OLD.credential_id_digest,
                            OLD.credential_data, OLD.rp_id)
       OR NEW.sign_count < OLD.sign_count
       OR (OLD.enrollment_verified_at IS NOT NULL AND NEW.enrollment_verified_at
           IS DISTINCT FROM OLD.enrollment_verified_at)
       OR (OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Director credential history is immutable';
    END IF;
    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;
"""

CHALLENGE_SQL = """
CREATE FUNCTION jireh_director_challenge_history() RETURNS trigger AS $body$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Director challenge history is immutable';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.closed_at IS NOT NULL OR NEW.verified_at IS NOT NULL
           OR NEW.verified_sign_count IS NOT NULL THEN
            RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Director challenge must start pending';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.closed_at IS NOT NULL OR
       ROW(NEW.id, NEW.created_at, NEW.credential_id, NEW.session_digest, NEW.challenge, NEW.expires_at)
       IS DISTINCT FROM
       ROW(OLD.id, OLD.created_at, OLD.credential_id, OLD.session_digest, OLD.challenge, OLD.expires_at) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Director challenge history is immutable';
    END IF;
    IF NEW.verified_at IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM schools_directorwebauthncredential c
        WHERE c.id=NEW.credential_id AND c.sign_count=NEW.verified_sign_count
          AND c.revoked_at IS NULL AND c.enrollment_verified_at IS NOT NULL
          AND c.enrollment_verified_at <= NEW.verified_at
          AND NEW.verified_at < NEW.expires_at
    ) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Director challenge counter evidence is inconsistent';
    END IF;
    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(CREDENTIAL_SQL)
        cursor.execute(CHALLENGE_SQL)
        cursor.execute("CREATE TRIGGER jireh_director_credential_history_trigger "
                       "BEFORE UPDATE OR DELETE ON schools_directorwebauthncredential "
                       "FOR EACH ROW EXECUTE FUNCTION jireh_director_credential_history()")
        cursor.execute("CREATE TRIGGER jireh_director_challenge_history_trigger "
                       "BEFORE INSERT OR UPDATE OR DELETE ON schools_directorwebauthnchallenge "
                       "FOR EACH ROW EXECUTE FUNCTION jireh_director_challenge_history()")


def remove(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP TRIGGER IF EXISTS jireh_director_challenge_history_trigger "
                       "ON schools_directorwebauthnchallenge")
        cursor.execute("DROP TRIGGER IF EXISTS jireh_director_credential_history_trigger "
                       "ON schools_directorwebauthncredential")
        cursor.execute("DROP FUNCTION IF EXISTS jireh_director_challenge_history()")
        cursor.execute("DROP FUNCTION IF EXISTS jireh_director_credential_history()")


class Migration(migrations.Migration):
    dependencies = [("schools", "0029_director_webauthn_acceptance")]
    operations = [migrations.RunPython(install, remove)]
