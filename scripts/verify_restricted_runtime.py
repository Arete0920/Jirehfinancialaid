"""Read-only preflight for the closed Jireh runtime on an authorized target."""

import argparse
import json
from contextlib import closing
from http.client import HTTPException, HTTPSConnection
from urllib.parse import urlsplit

from jireh.runtime.config import RuntimeConfigurationError, read_runtime_config


class PreflightError(ValueError):
    """A failed preflight with a shareable message."""


_CATALOG_CHECK = """
WITH principals AS (
    SELECT oid, rolname, rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls
    FROM pg_catalog.pg_roles
    WHERE rolname = CURRENT_USER OR pg_catalog.pg_has_role(oid, 'MEMBER')
), target_schema AS (
    SELECT oid, nspowner FROM pg_catalog.pg_namespace WHERE nspname = 'public'
), relations AS (
    SELECT c.oid, c.relowner, c.relkind, c.relname
    FROM pg_catalog.pg_class c JOIN target_schema n ON n.oid = c.relnamespace
    WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
)
SELECT
    SESSION_USER = %s AND CURRENT_USER = SESSION_USER,
    EXISTS (SELECT 1 FROM pg_catalog.pg_stat_ssl WHERE pid = pg_catalog.pg_backend_pid() AND ssl),
    NOT EXISTS (
        SELECT 1 FROM principals p JOIN pg_catalog.pg_database d ON d.datname = CURRENT_DATABASE()
        WHERE p.rolsuper OR p.rolcreaterole OR p.rolcreatedb OR p.rolreplication OR p.rolbypassrls
           OR pg_catalog.left(p.rolname::text, 3) = 'pg_'
           OR d.datdba = p.oid OR pg_catalog.has_database_privilege(p.oid, d.oid, 'CREATE')
    ),
    (SELECT count(*) FROM relations
        WHERE relkind IN ('r', 'p')
          AND relname IN ('django_migrations', 'auth_user', 'financial_aid_syntheticpendingpayment')) = 3
        AND NOT EXISTS (
            SELECT 1 FROM target_schema n CROSS JOIN principals p
            WHERE n.nspowner = p.oid OR pg_catalog.has_schema_privilege(p.oid, n.oid, 'CREATE')
        ),
    NOT EXISTS (
        SELECT 1 FROM relations r CROSS JOIN principals p
        WHERE r.relowner = p.oid OR CASE WHEN r.relkind = 'S'
            THEN pg_catalog.has_sequence_privilege(p.oid, r.oid, 'SELECT, USAGE, UPDATE')
            ELSE pg_catalog.has_table_privilege(p.oid, r.oid,
                    'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER')
                OR pg_catalog.has_any_column_privilege(p.oid, r.oid, 'SELECT, INSERT, UPDATE, REFERENCES')
            END
    )
"""

_DATABASE_FAILURES = (
    "runtime login identity mismatch",
    "database TLS absent",
    "runtime login can reach a predefined role or database administration",
    "schema incomplete or runtime login can create schema objects",
    "runtime login has direct access to an application table, view, or sequence",
)


def verify_probes(origin, config, *, outage=False):
    """Check strict response metadata and bodies without following redirects."""
    try:
        url = urlsplit(origin)
        port = url.port if url.port is not None else 443
        if (url.scheme != "https" or url.hostname not in config.allowed_hosts
                or url.username is not None or url.password is not None
                or url.path not in ("", "/") or url.query or url.fragment
                or any(char.isspace() for char in origin) or not 1 <= port <= 65535):
            raise ValueError()
    except ValueError:
        raise PreflightError("HTTPS origin must match a configured allowed host") from None

    readiness = (503, "unavailable") if outage else (200, "ready")
    with closing(HTTPSConnection(url.hostname, port, timeout=5)) as connection:
        for path, status, expected in (("/healthz/", 200, "alive"), ("/readyz/", *readiness)):
            try:
                connection.request("GET", path, headers={"Accept": "application/json"})
                response = connection.getresponse()
                content_type = (response.getheader("Content-Type") or "").split(";", 1)[0].strip().lower()
                body = response.read(1025)
                if (response.status != status or content_type != "application/json" or len(body) > 1024
                        or json.loads(body, object_pairs_hook=tuple) != (("status", expected),)):
                    raise ValueError()
            except (OSError, HTTPException, ValueError, RecursionError):
                raise PreflightError(f"unexpected or unavailable response for {path}") from None


def verify_database(config):
    """Verify a separate connection as the configured login using catalog reads."""
    import psycopg

    try:
        with psycopg.connect(
            host=config.db_host, port=config.db_port, dbname=config.db_name,
            user=config.db_user, password=config.db_password, connect_timeout=5,
            sslmode="verify-full", sslrootcert=config.db_sslrootcert, gssencmode="disable",
            options="-c default_transaction_read_only=on -c statement_timeout=5000",
        ) as connection:
            row = connection.execute(_CATALOG_CHECK, (config.db_user,)).fetchone()
    except psycopg.Error:
        raise PreflightError("database connection or catalog check failed") from None
    if (type(row) is not tuple or len(row) != len(_DATABASE_FAILURES)
            or any(type(value) is not bool for value in row)):
        raise PreflightError("database catalog evidence incomplete")
    for check, error in zip(row, _DATABASE_FAILURES, strict=True):
        if not check:
            raise PreflightError(error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin", help="Approved HTTPS origin for the closed runtime")
    parser.add_argument("--outage", action="store_true", help="Observe an independently authorized outage")
    args = parser.parse_args()
    try:
        config = read_runtime_config()
        verify_probes(args.origin, config, outage=args.outage)
        if not args.outage:
            verify_database(config)
    except RuntimeConfigurationError:
        parser.exit(1, "FAIL: required runtime configuration is missing or invalid\n")
    except PreflightError as error:
        parser.exit(1, f"FAIL: {error}\n")
    evidence = "liveness 200, readiness 503" if args.outage else "probes 200, verified database TLS and direct ACLs"
    print(f"PASS: restricted runtime probes ({evidence})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
