"""Disposable acceptance for the standalone process and database probes.

Do not use this test as operational deployment or production readiness evidence.
"""

from unittest.mock import MagicMock, patch

from django.db import DatabaseError
from django.test import TestCase, override_settings


@override_settings(ROOT_URLCONF="jireh.runtime.urls")
class RuntimeReadinessTests(TestCase):
    def test_database_roundtrip_returns_only_non_sensitive_ready_status(self):
        response = self.client.get("/readyz/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready"})
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(self.client.head("/readyz/").status_code, 200)

    def test_database_failure_is_fail_closed_without_exception_disclosure(self):
        with patch(
            "jireh.runtime.urls.connection.cursor",
            side_effect=DatabaseError("SECRET db.example.invalid password leaked"),
        ):
            response = self.client.get("/readyz/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn("SECRET", response.content.decode())
        self.assertNotIn("db.example.invalid", response.content.decode())

    def test_unexpected_database_result_is_unavailable(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (0,)
        manager = MagicMock()
        manager.__enter__.return_value = cursor
        with patch("jireh.runtime.urls.connection.cursor", return_value=manager):
            response = self.client.get("/readyz/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})
        cursor.execute.assert_called_once_with("SELECT 1")

    def test_liveness_independent_of_database_failure(self):
        with patch(
            "jireh.runtime.urls.connection.cursor",
            side_effect=DatabaseError("database unavailable"),
        ):
            response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "alive"})

    def test_closed_runtime_routes_and_method_restrictions_remain(self):
        for path in ("/readyz/", "/healthz/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path).status_code, 405)
        for path in ("/api/v1/", "/local-demo/", "/admin/", "/login/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)
