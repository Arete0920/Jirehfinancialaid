"""Evidence contract tests; PostgreSQL catalog acceptance is separate."""
from unittest.mock import MagicMock

from django.db import DatabaseError, connection
from django.test import SimpleTestCase, TestCase
from unittest import skipUnless

from jireh.runtime.db_privilege_audit import audit_fictional_journal_privileges


class JournalPrivilegeAuditContractTests(SimpleTestCase):
    GOOD = (True, False, False, 1, False, 2, False, False)

    def audit(self, row):
        conn = MagicMock(vendor="postgresql")
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = row
        return audit_fictional_journal_privileges(conn, schema="public"), cursor

    def test_complete_direct_evidence_is_not_release_authority(self):
        result, cursor = self.audit(self.GOOD)
        self.assertTrue(result.direct_acl_pass)
        self.assertFalse(result.authorizes_release)
        self.assertEqual(result.blocking_reasons, ())
        sql, params = cursor.execute.call_args.args
        self.assertEqual(params, ("public", "financial_aid_fictionalneeddecision",
                                  "financial_aid_fictionalincomeevidencereview"))
        self.assertIn("pg_catalog.has_any_column_privilege", sql)
        self.assertIn("pg_catalog.pg_has_role", sql)

    def test_every_unsafe_or_missing_fact_blocks(self):
        for index, value, reason in (
            (0, False, "session_role_mismatch"),
            (1, True, "administrative_role_reachable"),
            (2, True, "database_owner_reachable"),
            (3, 0, "target_schema_missing"),
            (4, True, "schema_create_or_owner_reachable"),
            (5, 1, "journal_tables_missing"),
            (6, True, "journal_owner_reachable"),
            (7, True, "journal_direct_privilege_reachable"),
        ):
            with self.subTest(reason=reason):
                row = list(self.GOOD)
                row[index] = value
                result, _ = self.audit(tuple(row))
                self.assertFalse(result.direct_acl_pass)
                self.assertEqual(result.blocking_reasons, (reason,))
                self.assertFalse(result.authorizes_release)

    def test_invalid_results_fail_closed(self):
        for row in (None, (), list(self.GOOD), (1, *self.GOOD[1:]),
                    (*self.GOOD[:3], True, *self.GOOD[4:])):
            with self.subTest(row=row):
                result, _ = self.audit(row)
                self.assertFalse(result.direct_acl_pass)
                self.assertEqual(result.blocking_reasons, ("catalog_evidence_invalid",))

    def test_database_failure_is_sanitized(self):
        conn = MagicMock(vendor="postgresql")
        conn.cursor.side_effect = DatabaseError("private database connection detail")
        result = audit_fictional_journal_privileges(conn, schema="public")
        self.assertEqual(result.blocking_reasons, ("catalog_query_failed",))
        self.assertFalse(result.direct_acl_pass)
        self.assertNotIn("private", repr(result))

    def test_wrong_backend_or_schema_never_queries_database(self):
        conn = MagicMock(vendor="sqlite")
        self.assertEqual(audit_fictional_journal_privileges(conn, schema="public").blocking_reasons,
                         ("postgresql_required",))
        conn.vendor = "postgresql"
        for invalid in (None, "", "\x00", "x" * 64):
            self.assertEqual(audit_fictional_journal_privileges(conn, schema=invalid).blocking_reasons,
                             ("schema_invalid",))
        conn.cursor.assert_not_called()


@skipUnless(connection.vendor == "postgresql", "Actual PostgreSQL catalog required")
class JournalPrivilegeAuditPostgresTests(TestCase):
    def test_existing_disposable_owner_is_rejected_and_journals_are_found(self):
        # The CI database is created by its disposable admin login. This
        # exercises the exact query, not a simulated production credential.
        result = audit_fictional_journal_privileges(connection, schema="public")
        self.assertFalse(result.direct_acl_pass)
        self.assertIn("database_owner_reachable", result.blocking_reasons)
        self.assertIn("journal_owner_reachable", result.blocking_reasons)
        self.assertIn("journal_direct_privilege_reachable", result.blocking_reasons)
        self.assertNotIn("catalog_query_failed", result.blocking_reasons)
        self.assertNotIn("journal_tables_missing", result.blocking_reasons)

    def test_disposable_restricted_role_and_indirect_column_grant(self):
        import os
        from uuid import uuid4
        from django.db import transaction

        # This is a transactional CI-only role fixture, never a target DB
        # grant script. Require the existing localhost disposable configuration.
        self.assertEqual(os.environ.get("JIREH_POSTGRES_CI_ONLY"), "1")
        self.assertEqual(connection.settings_dict["HOST"], "127.0.0.1")
        self.assertEqual(connection.settings_dict["NAME"], "test_jireh_ci")
        login = "jireh_acl_test_" + uuid4().hex
        group = "jireh_acl_group_" + uuid4().hex
        with connection.cursor() as cursor:
            # The identifiers are generated locally from lowercase UUID hex.
            cursor.execute(f"CREATE ROLE {login} NOLOGIN NOINHERIT")
            cursor.execute(f"CREATE ROLE {group} NOLOGIN")
            cursor.execute(f"GRANT USAGE ON SCHEMA public TO {login}")

        def as_restricted_user():
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(f"SET LOCAL SESSION AUTHORIZATION {login}")
                try:
                    return audit_fictional_journal_privileges(connection, schema="public")
                finally:
                    with connection.cursor() as cursor:
                        cursor.execute("RESET SESSION AUTHORIZATION")

        self.assertTrue(as_restricted_user().direct_acl_pass)
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f"SET LOCAL SESSION AUTHORIZATION {login}")
            try:
                with self.assertRaises(DatabaseError) as denied, transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("INSERT INTO public.financial_aid_fictionalneeddecision DEFAULT VALUES")
                cause = denied.exception.__cause__
                self.assertEqual(getattr(cause, "sqlstate", getattr(cause, "pgcode", None)), "42501")
            finally:
                with connection.cursor() as cursor:
                    cursor.execute("RESET SESSION AUTHORIZATION")
        with connection.cursor() as cursor:
            cursor.execute(f"GRANT UPDATE (need_cents) ON public.financial_aid_fictionalneeddecision TO {group}")
            cursor.execute(f"GRANT {group} TO {login}")
        result = as_restricted_user()
        self.assertFalse(result.direct_acl_pass)
        self.assertEqual(result.blocking_reasons, ("journal_direct_privilege_reachable",))
        # The TestCase's outer transaction rolls back both role creations and grants.
