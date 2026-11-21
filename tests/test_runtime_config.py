"""Pure-Python security contracts for the not-yet-deployed runtime."""

from pathlib import Path
import tempfile
import unittest

from jireh.runtime.config import RuntimeConfigurationError, read_runtime_config


class RuntimeConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        ca = Path(self.tmp.name) / "placeholder-ca.pem"
        ca.write_text("CI fixture, not a real CA\n", encoding="utf-8")
        self.config = {
            "JIREH_ENABLE_RUNTIME": "1",
            "JIREH_SECRET_KEY": "not-production-" + "a" * 56,
            "JIREH_ALLOWED_HOSTS": "jireh.example.invalid,localhost",
            "JIREH_DB_NAME": "jireh_test",
            "JIREH_DB_USER": "jireh_test",
            "JIREH_DB_PASSWORD": "not-a-real-db-password",
            "JIREH_DB_HOST": "db.example.invalid",
            "JIREH_DB_PORT": "5432",
            "JIREH_DB_SSLROOTCERT": str(ca),
        }

    def test_valid_explicit_configuration(self):
        actual = read_runtime_config(self.config)
        self.assertEqual(actual.allowed_hosts, ("jireh.example.invalid", "localhost"))
        self.assertEqual(actual.db_port, 5432)
        self.assertEqual(actual.db_host, "db.example.invalid")
        self.assertEqual(actual.db_password, "not-a-real-db-password")

    def test_disabled_or_missing_runtime_fails_closed(self):
        for value in (None, "", "0", "true"):
            with self.subTest(value=value):
                values = self.config.copy()
                if value is None:
                    values.pop("JIREH_ENABLE_RUNTIME")
                else:
                    values["JIREH_ENABLE_RUNTIME"] = value
                with self.assertRaises(RuntimeConfigurationError):
                    read_runtime_config(values)

    def test_every_critical_parameter_is_required(self):
        names = [
            "JIREH_SECRET_KEY", "JIREH_ALLOWED_HOSTS", "JIREH_DB_NAME",
            "JIREH_DB_USER", "JIREH_DB_PASSWORD", "JIREH_DB_HOST",
            "JIREH_DB_SSLROOTCERT",
        ]
        for name in names:
            with self.subTest(name=name):
                values = self.config.copy()
                values.pop(name)
                with self.assertRaises(RuntimeConfigurationError):
                    read_runtime_config(values)

    def test_insecure_hosts_are_rejected(self):
        for hosts in ("*", "example.com,*", "https://example.com", "example.com:443", ".example.com", "example.com/evil", "localhost,,example.com", "example.com,example.com"):
            with self.subTest(hosts=hosts):
                values = {**self.config, "JIREH_ALLOWED_HOSTS": hosts}
                with self.assertRaises(RuntimeConfigurationError):
                    read_runtime_config(values)

    def test_invalid_secrets_and_database_transport_are_rejected(self):
        modifications = (
            ("JIREH_SECRET_KEY", "short"),
            ("JIREH_SECRET_KEY", "test-only--" + "x" * 60),
            ("JIREH_SECRET_KEY", "x" * 55 + "\n"),
            ("JIREH_DB_HOST", "postgres://db.example.invalid"),
            ("JIREH_DB_PORT", "0"),
            ("JIREH_DB_PORT", "65536"),
            ("JIREH_DB_PORT", "abc"),
            ("JIREH_DB_SSLROOTCERT", "relative-ca.pem"),
            ("JIREH_DB_SSLROOTCERT", "/no/such/jireh-ca.pem"),
        )
        for name, value in modifications:
            with self.subTest(name=name, value=value):
                with self.assertRaises(RuntimeConfigurationError):
                    read_runtime_config({**self.config, name: value})

    def test_config_repr_does_not_leak_credentials_or_depend_on_crown(self):
        rendered = repr(read_runtime_config(self.config))
        self.assertNotIn(self.config["JIREH_SECRET_KEY"], rendered)
        self.assertNotIn(self.config["JIREH_DB_PASSWORD"], rendered)
        self.assertNotIn("CROWN", rendered)


if __name__ == "__main__":
    unittest.main()
