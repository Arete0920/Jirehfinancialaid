from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from scripts.verify_restricted_runtime import PreflightError, verify_probes


class Response:
    def __init__(self, status, body):
        self.status = status
        self.body = body

    def getheader(self, name):
        return "application/json" if name == "Content-Type" else None

    def read(self, limit):
        return self.body[:limit]


class RestrictedRuntimePreflightTests(TestCase):
    def probe(self, responses, *, outage=False, origin="https://acceptance.example.invalid"):
        config = SimpleNamespace(allowed_hosts=("acceptance.example.invalid",))
        with patch("scripts.verify_restricted_runtime.HTTPSConnection") as connection:
            connection.return_value.getresponse.side_effect = responses
            verify_probes(origin, config, outage=outage)
            return connection

    def test_normal_and_outage_probe_expectations(self):
        for outage, status, body in ((False, 200, b'{"status":"ready"}'),
                                     (True, 503, b'{"status":"unavailable"}')):
            with self.subTest(outage=outage):
                connection = self.probe([Response(200, b'{"status":"alive"}'), Response(status, body)], outage=outage)
                connection.assert_called_once_with("acceptance.example.invalid", 443, timeout=5)
                methods = [call.args[:2] for call in connection.return_value.request.call_args_list]
                self.assertEqual(methods, [("GET", "/healthz/"), ("GET", "/readyz/")])

    def test_cli_selects_only_a_configured_https_destination(self):
        config = SimpleNamespace(allowed_hosts=("first.example.invalid", "second.example.invalid"))
        with patch("scripts.verify_restricted_runtime.HTTPSConnection") as connection:
            connection.return_value.getresponse.side_effect = [
                Response(200, b'{"status":"alive"}'), Response(200, b'{"status":"ready"}'),
            ]
            verify_probes("https://second.example.invalid:443/", config)
            connection.assert_called_once_with(config.allowed_hosts[1], 443, timeout=5)

        for origin in (
            "https://second.example.invalid:8443", "https://second.example.invalid:0443",
            "https://second.example.invalid@outside.example.invalid",
            "https://second.example.invalid.outside.example.invalid",
            "https://second.example.invalid?", "https://second.example.invalid#",
            "https://second.example.invalid/%2f", " https://second.example.invalid",
            "https://127.0.0.1", "https://169.254.169.254", None,
        ):
            with self.subTest(origin=origin), patch("scripts.verify_restricted_runtime.HTTPSConnection") as connection:
                with self.assertRaisesRegex(PreflightError, "origin"):
                    verify_probes(origin, config)
                connection.assert_not_called()

    def test_unapproved_origins_redirects_and_extra_response_fields_fail(self):
        for origin in ("http://acceptance.example.invalid", "https://outside.example.invalid",
                       "https://acceptance.example.invalid/private", "https://a@acceptance.example.invalid"):
            with self.subTest(origin=origin), self.assertRaisesRegex(PreflightError, "origin"):
                self.probe([], origin=origin)
        for reply in (Response(302, b'{"status":"alive"}'), Response(200, b"[" * 1024),
                      Response(200, b'{"status":"alive","notice":"unexpected"}'),
                      Response(200, b'{"status":"unexpected","status":"alive"}')):
            with self.subTest(reply=reply.body), self.assertRaisesRegex(PreflightError, "healthz"):
                self.probe([reply])
