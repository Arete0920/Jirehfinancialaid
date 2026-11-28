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
                methods = [call.args[:2] for call in connection.return_value.request.call_args_list]
                self.assertEqual(methods, [("GET", "/healthz/"), ("GET", "/readyz/")])

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
