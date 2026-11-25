"""Read-only evidence for the fictional journal's direct database ACL boundary.

Run only with an independently authorized connection using the actual runtime
login. This is not a full privilege, RLS, function, view, TLS or release audit.
No database changes, role changes, customer route or secret output.
"""
from dataclasses import dataclass


# Explicitly rehearsal-only journal tables, not the future live award ledger.
_JOURNALS = (
    "financial_aid_fictionalneeddecision",
    "financial_aid_fictionalincomeevidencereview",
)

# Check all reachable memberships conservatively, including roles whose
# privileges might be obtained with SET ROLE. Catalog lookup is parameterized.
# Do not rely on information_schema grants, which omit some effective rights.
_SQL = """
WITH principals AS (
    SELECT oid, rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls
    FROM pg_catalog.pg_roles
    WHERE rolname = CURRENT_USER OR pg_catalog.pg_has_role(oid, 'MEMBER')
), target_schema AS (
    SELECT oid, nspowner FROM pg_catalog.pg_namespace WHERE nspname = %s
), journals AS (
    SELECT c.oid, c.relowner, c.relname
    FROM pg_catalog.pg_class c JOIN target_schema n ON n.oid = c.relnamespace
    WHERE c.relname IN (%s, %s) AND c.relkind IN ('r', 'p')
)
SELECT
    CURRENT_USER = SESSION_USER,
    EXISTS (SELECT 1 FROM principals WHERE rolsuper OR rolcreaterole
            OR rolcreatedb OR rolreplication OR rolbypassrls),
    EXISTS (SELECT 1 FROM pg_catalog.pg_database d JOIN principals p
            ON d.datdba = p.oid WHERE d.datname = CURRENT_DATABASE()),
    (SELECT count(*) FROM target_schema),
    EXISTS (SELECT 1 FROM target_schema n CROSS JOIN principals p
            WHERE n.nspowner = p.oid
               OR pg_catalog.has_schema_privilege(p.oid, n.oid, 'CREATE')),
    (SELECT count(*) FROM journals),
    EXISTS (SELECT 1 FROM journals j CROSS JOIN principals p
            WHERE j.relowner = p.oid),
    EXISTS (SELECT 1 FROM journals j CROSS JOIN principals p
            WHERE pg_catalog.has_table_privilege(p.oid, j.oid,
                    'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER')
               OR pg_catalog.has_any_column_privilege(p.oid, j.oid,
                    'SELECT, INSERT, UPDATE, REFERENCES'))
"""


@dataclass(frozen=True, slots=True)
class JournalPrivilegeAudit:
    direct_acl_pass: bool
    blocking_reasons: tuple[str, ...]
    authorizes_release: bool = False


def audit_fictional_journal_privileges(connection, *, schema: str) -> JournalPrivilegeAudit:
    """Check direct ACLs only; unknown or incomplete evidence fails closed.

    The application writer remains trusted to calculate need. This check does
    not make that calculation independently verifiable by PostgreSQL. It tests
    whether a customer login can directly reach the rehearsal journals, own
    them, or administer the target schema/database. A separate audit must
    establish indirect paths, role topology and live-ledger permissions.
    """
    if connection.vendor != "postgresql":
        return JournalPrivilegeAudit(False, ("postgresql_required",))
    if type(schema) is not str or not schema or len(schema.encode("utf-8")) > 63 or "\x00" in schema:
        return JournalPrivilegeAudit(False, ("schema_invalid",))
    from django.db import DatabaseError
    try:
        with connection.cursor() as cursor:
            cursor.execute(_SQL, (schema, *_JOURNALS))
            row = cursor.fetchone()
    except DatabaseError:
        return JournalPrivilegeAudit(False, ("catalog_query_failed",))
    if (type(row) is not tuple or len(row) != 8
            or any(type(row[i]) is not bool for i in (0, 1, 2, 4, 6, 7))
            or any(type(row[i]) is not int for i in (3, 5))):
        return JournalPrivilegeAudit(False, ("catalog_evidence_invalid",))
    reasons = tuple(reason for condition, reason in (
        (not row[0], "session_role_mismatch"),
        (row[1], "administrative_role_reachable"),
        (row[2], "database_owner_reachable"),
        (row[3] != 1, "target_schema_missing"),
        (row[4], "schema_create_or_owner_reachable"),
        (row[5] != len(_JOURNALS), "journal_tables_missing"),
        (row[6], "journal_owner_reachable"),
        (row[7], "journal_direct_privilege_reachable"),
    ) if condition)
    return JournalPrivilegeAudit(not reasons, reasons)
