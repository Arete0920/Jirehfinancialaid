"""Version 1 of the disposable PostgreSQL document-recovery grants and procedures."""

import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from secrets import token_hex
from uuid import UUID, uuid4

from psycopg import sql


@dataclass(frozen=True)
class RecoveryProvision:
    operator_role: str
    storage_role: str
    operator_password: str = field(repr=False)
    storage_password: str = field(repr=False)
    claim: str
    confirm: str
    finish: str
    receipts: str


@contextmanager
def provision_recovery_v1(connection, *, school_id, operator_id):
    """Provision one disposable assignment and remove its roles and objects on exit."""
    if (os.environ.get("JIREH_POSTGRES_CI_ONLY") != "1" or type(school_id) is not UUID
            or type(operator_id) is not int or operator_id < 1 or not connection.autocommit
            or connection.info.hostaddr != "127.0.0.1"):
        raise ValueError("Disposable recovery provisioning required")
    guard = connection.execute("""
        SELECT current_database() = 'test_jireh_ci'
            AND current_user = 'jireh_ci' AND session_user = current_user
            AND EXISTS (
                SELECT 1 FROM pg_catalog.pg_database
                WHERE datname = current_database() AND datdba = current_user::regrole::oid
            )
            AND EXISTS (
                SELECT 1 FROM pg_catalog.pg_namespace
                WHERE nspname = 'public' AND nspowner IN ('pg_database_owner'::regrole, current_user::regrole)
            )
            AND NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_namespace AS schema
                CROSS JOIN LATERAL pg_catalog.aclexplode(
                    coalesce(schema.nspacl, pg_catalog.acldefault('n', schema.nspowner))
                ) AS grant_entry
                WHERE schema.nspname = 'public' AND grant_entry.privilege_type = 'CREATE'
                  AND grant_entry.grantee <> schema.nspowner
            )
    """).fetchone()
    if guard != (True,):
        raise ValueError("Disposable recovery database or schema privileges rejected")

    tag = uuid4().hex
    login = f"jireh_worker_v1_{tag}"
    password = token_hex(24)
    storage_login = f"jireh_storage_v1_{tag}"
    storage_password = token_hex(24)
    worker_role = sql.Identifier(login)
    storage_role = sql.Identifier(storage_login)
    owner_role = sql.Identifier(f"jireh_recovery_owner_v1_{tag}")
    claim_name = f"jireh_recovery_claim_v1_{tag}"
    confirm_name = f"jireh_recovery_confirm_v1_{tag}"
    finish_name = f"jireh_recovery_finish_v1_{tag}"
    receipt_name = f"jireh_recovery_receipts_v1_{tag}"
    claim = sql.Identifier("public", claim_name)
    confirm = sql.Identifier("public", confirm_name)
    finish = sql.Identifier("public", finish_name)
    receipts = sql.Identifier("public", receipt_name)

    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE ROLE {} LOGIN NOINHERIT PASSWORD {}").format(
            worker_role, sql.Literal(password),
        ))
        cursor.execute(sql.SQL("CREATE ROLE {} LOGIN NOINHERIT PASSWORD {}").format(
            storage_role, sql.Literal(storage_password),
        ))
        cursor.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOINHERIT").format(owner_role))
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}, {}, {}").format(
            worker_role, storage_role, owner_role,
        ))
        cursor.execute(sql.SQL("""
            CREATE TABLE {} (
                school_id uuid NOT NULL,
                document_id uuid PRIMARY KEY,
                object_key uuid NOT NULL,
                confirmed_by name NOT NULL,
                confirmed_at timestamptz NOT NULL DEFAULT clock_timestamp()
            )
        """).format(receipts))
        cursor.execute(sql.SQL("REVOKE ALL ON TABLE {} FROM PUBLIC").format(receipts))
        cursor.execute(sql.SQL("GRANT SELECT, INSERT ON {} TO {}").format(receipts, owner_role))
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM pg_catalog.unnest(%s::name[]) AS caller(role_name)
                CROSS JOIN pg_catalog.unnest(%s::text[]) AS subject(table_name)
                WHERE pg_catalog.has_table_privilege(caller.role_name, subject.table_name,
                        'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER')
                   OR pg_catalog.has_any_column_privilege(caller.role_name, subject.table_name,
                        'SELECT, INSERT, UPDATE, REFERENCES')
            )
        """, ([login, storage_login], [
            "public.auth_user", "public.schools_school", "public.financial_aid_aidapplication",
            "public.financial_aid_financialdocument", "public.financial_aid_financialdocumentevent",
            f"public.{receipt_name}",
        ]))
        if cursor.fetchone() != (False,):
            raise ValueError("Direct recovery table privileges rejected")
        for grant in (
            "SELECT (id,is_active,is_staff,is_superuser), UPDATE (last_login) ON public.auth_user",
            "SELECT (id,is_active), UPDATE (name) ON public.schools_school",
            "SELECT (id,status,school_id,household_id,academic_year_id), UPDATE (updated_at)"
            " ON public.financial_aid_aidapplication",
            "SELECT (id,school_id,application_id,state,object_key), UPDATE (state,deleted_at,updated_at)"
            " ON public.financial_aid_financialdocument",
            "SELECT (id,school_id) ON public.schools_household, public.schools_academicyear",
            "INSERT (id,created_at,updated_at,action,actor_user_id,document_id,school_id)"
            " ON public.financial_aid_financialdocumentevent",
        ):
            cursor.execute(sql.SQL("GRANT " + grant + " TO {}").format(owner_role))

        cursor.execute(sql.SQL("""
            CREATE FUNCTION {}(p_school uuid, p_document uuid) RETURNS uuid
            LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $body$
            DECLARE object_id uuid;
            BEGIN
                IF SESSION_USER NOT IN ({}, {}) OR p_school IS DISTINCT FROM {}::uuid THEN
                    RETURN NULL;
                END IF;
                PERFORM 1 FROM public.schools_school WHERE id=p_school AND is_active FOR UPDATE;
                IF NOT FOUND THEN RETURN NULL; END IF;
                PERFORM 1 FROM public.auth_user
                    WHERE id={} AND is_active AND is_staff AND NOT is_superuser FOR UPDATE;
                IF NOT FOUND THEN RETURN NULL; END IF;
                SELECT d.object_key INTO object_id
                FROM public.financial_aid_financialdocument d
                JOIN public.financial_aid_aidapplication a ON a.id=d.application_id
                WHERE d.id=p_document AND d.school_id=p_school AND a.school_id=p_school
                  AND a.status='DRAFT' AND d.state='DELETE_PENDING'
                FOR UPDATE OF a,d;
                RETURN object_id;
            END;
            $body$
        """).format(claim, sql.Literal(login), sql.Literal(storage_login),
                    sql.Literal(str(school_id)), sql.Literal(operator_id)))
        cursor.execute(sql.SQL("""
            CREATE FUNCTION {}(p_school uuid, p_document uuid) RETURNS boolean
            LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $body$
            DECLARE object_id uuid;
            BEGIN
                IF SESSION_USER <> {} THEN RETURN FALSE; END IF;
                object_id := {}(p_school,p_document);
                IF object_id IS NULL THEN RETURN FALSE; END IF;
                INSERT INTO {} (school_id,document_id,object_key,confirmed_by)
                VALUES (p_school,p_document,object_id,SESSION_USER)
                ON CONFLICT (document_id) DO NOTHING;
                RETURN TRUE;
            END;
            $body$
        """).format(confirm, sql.Literal(storage_login), claim, receipts))
        cursor.execute(sql.SQL("""
            CREATE FUNCTION {}(p_school uuid, p_document uuid) RETURNS boolean
            LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $body$
            DECLARE object_id uuid;
            BEGIN
                IF SESSION_USER <> {} THEN RETURN FALSE; END IF;
                object_id := {}(p_school,p_document);
                IF object_id IS NULL OR NOT EXISTS (
                    SELECT 1 FROM {}
                    WHERE school_id=p_school AND document_id=p_document
                      AND object_key=object_id AND confirmed_by={}
                ) THEN RETURN FALSE; END IF;
                UPDATE public.financial_aid_financialdocument
                SET state='DELETED', deleted_at=transaction_timestamp(), updated_at=transaction_timestamp()
                WHERE id=p_document AND school_id=p_school AND state='DELETE_PENDING';
                IF NOT FOUND THEN RETURN FALSE; END IF;
                INSERT INTO public.financial_aid_financialdocumentevent
                    (id,created_at,updated_at,action,actor_user_id,document_id,school_id)
                VALUES (gen_random_uuid(),transaction_timestamp(),transaction_timestamp(),
                        'DELETED',{},p_document,p_school);
                RETURN TRUE;
            END;
            $body$
        """).format(finish, sql.Literal(login), claim, receipts,
                    sql.Literal(storage_login), sql.Literal(operator_id)))
        for function, caller in (
            (claim, storage_role), (confirm, storage_role), (finish, worker_role),
        ):
            cursor.execute(sql.SQL("ALTER FUNCTION {}(uuid,uuid) OWNER TO {}").format(function, owner_role))
            cursor.execute(sql.SQL("REVOKE ALL ON FUNCTION {}(uuid,uuid) FROM PUBLIC").format(function))
            cursor.execute(sql.SQL("GRANT EXECUTE ON FUNCTION {}(uuid,uuid) TO {}").format(function, caller))


    try:
        yield RecoveryProvision(login, storage_login, password, storage_password,
                                claim_name, confirm_name, finish_name, receipt_name)
    finally:
        with connection.transaction(), connection.cursor() as cursor:
            for function in (finish, confirm, claim):
                cursor.execute(sql.SQL("DROP FUNCTION {}(uuid,uuid)").format(function))
            cursor.execute(sql.SQL("DROP TABLE {}").format(receipts))
            for role in (worker_role, storage_role, owner_role):
                cursor.execute(sql.SQL("DROP OWNED BY {}").format(role))
                cursor.execute(sql.SQL("DROP ROLE {}").format(role))
