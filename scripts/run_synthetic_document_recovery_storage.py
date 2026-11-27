"""Run one synthetic storage job against the disposable local PostgreSQL database."""
import argparse
import json
import os
import re
import stat
import sys
from uuid import UUID

import psycopg
from psycopg import sql

from jireh.financial_aid.local_encrypted_backend import LocalEncryptedDocumentDeleter


_NAME = re.compile(r"[a-z][a-z0-9_]{0,62}\Z")
_FIELDS = {"role", "password", "root", "device", "inode", "claim", "confirm"}
_OPTIONS = "-c lock_timeout=500ms -c statement_timeout=2s -c idle_in_transaction_session_timeout=3s"


def _read_launch_config(file):
    metadata = os.fstat(file.fileno())
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600):
        raise ValueError("Private launch configuration required")
    raw = file.read(16_385)
    if len(raw) > 16_384:
        raise ValueError("Launch configuration too large")
    config = json.loads(raw)
    if (type(config) is not dict or set(config) != _FIELDS
            or any(type(config[key]) is not str or not _NAME.fullmatch(config[key])
                   for key in ("role", "claim", "confirm"))
            or not config["role"].startswith("jireh_storage_")
            or not config["claim"].startswith("jireh_recovery_claim_")
            or not config["confirm"].startswith("jireh_recovery_confirm_")
            or type(config["password"]) is not str or not config["password"]
            or type(config["root"]) is not str
            or any(type(config[key]) is not int or config[key] < 0 for key in ("device", "inode"))):
        raise ValueError("Invalid launch configuration")
    return config


def run_storage_job(config, school_id, document_id):
    if os.environ.get("JIREH_POSTGRES_CI_ONLY") != "1":
        raise ValueError("Disposable PostgreSQL rehearsal opt-in required")
    deleter = LocalEncryptedDocumentDeleter(
        root=config["root"], root_identity=(config["device"], config["inode"]),
    )
    claim = sql.SQL("SELECT {}(%s, %s)").format(sql.Identifier("public", config["claim"]))
    confirm = sql.SQL("SELECT {}(%s, %s)").format(sql.Identifier("public", config["confirm"]))
    scope = (school_id, document_id)
    with psycopg.connect(
        host="127.0.0.1", hostaddr="127.0.0.1", port=5432, dbname="test_jireh_ci",
        user=config["role"], password=config["password"], connect_timeout=3,
        require_auth="scram-sha-256", sslmode="disable", options=_OPTIONS, autocommit=True,
    ) as connection, connection.transaction():
        role = connection.execute("""
            SELECT session_user = %s AND current_user = session_user
                   AND NOT (rolsuper OR rolcreaterole OR rolcreatedb OR rolreplication OR rolbypassrls)
                   AND NOT EXISTS (
                       SELECT 1 FROM pg_catalog.pg_roles AS inherited
                       WHERE inherited.rolname <> current_user
                         AND pg_catalog.pg_has_role(inherited.oid, 'MEMBER')
                   )
                   AND NOT EXISTS (
                       SELECT 1 FROM pg_catalog.pg_database
                       WHERE datname = current_database() AND datdba = worker.oid
                   )
            FROM pg_catalog.pg_roles AS worker WHERE rolname = current_user
        """, (config["role"],)).fetchone()
        if role != (True,):
            raise ValueError("Restricted storage role required")
        row = connection.execute(claim, scope).fetchone()
        if row == (None,):
            return False
        if not row or type(row[0]) is not UUID:
            raise ValueError("Invalid storage claim")
        deleter.delete(str(row[0]))
        if connection.execute(confirm, scope).fetchone() != (True,):
            raise ValueError("Storage confirmation rejected")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("school", type=UUID)
    parser.add_argument("document", type=UUID)
    args = parser.parse_args()
    try:
        result = run_storage_job(_read_launch_config(sys.stdin.buffer), args.school, args.document)
    except (OSError, ValueError, psycopg.Error):
        print("storage_worker_failed")
        return 1
    print("storage_confirmed" if result else "no_pending_document")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
