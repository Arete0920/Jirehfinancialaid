"""Privacy and integrity tests for closed-runtime request telemetry."""

import json
from unittest.mock import patch
from uuid import UUID

from django.db import DatabaseError
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from jireh.runtime.telemetry import RuntimeRequestCorrelationMiddleware


class RuntimeCorrelationTests(TestCase):
    @override_settings(
        ROOT_URLCONF="jireh.runtime.urls",
        MIDDLEWARE=["jireh.runtime.telemetry.RuntimeRequestCorrelationMiddleware"],
    )
    def test_liveness_generates_new_server_ids_and_minimal_events(self):
        supplied = "UNTRUSTED-TOKEN-DO-NOT-LOG"
        with patch("jireh.runtime.telemetry.logger.info") as info:
            first = self.client.get(
                "/healthz/", HTTP_X_CORRELATION_ID=supplied,
                HTTP_X_REQUEST_ID=supplied,
            )
            second = self.client.head("/healthz/")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        first_id = first["X-Correlation-ID"]
        second_id = second["X-Correlation-ID"]
        self.assertNotEqual(first_id, second_id)
        self.assertNotEqual(first_id, supplied)
        self.assertEqual(str(UUID(first_id)), first_id)
        self.assertEqual(str(UUID(second_id)), second_id)
        self.assertEqual(info.call_count, 2)
        event = json.loads(info.call_args_list[0].args[0])
        self.assertEqual(
            set(event),
            {
                "event_type", "timestamp", "correlation_id", "route",
                "method", "status_code", "duration_ms",
            },
        )
        self.assertEqual(event["route"], "process_liveness")
        self.assertEqual(event["correlation_id"], first_id)
        self.assertEqual(event["status_code"], 200)
        self.assertEqual(event["method"], "GET")
        self.assertNotIn(supplied, str(info.call_args_list))
        self.assertNotIn("tenant_id", str(info.call_args_list))
        self.assertNotIn("user_id", str(info.call_args_list))

    @override_settings(
        ROOT_URLCONF="jireh.runtime.urls",
        MIDDLEWARE=["jireh.runtime.telemetry.RuntimeRequestCorrelationMiddleware"],
    )
    def test_closed_routes_never_log_raw_path_or_query(self):
        secret = "SECRET-SCHOOL-HOUSEHOLD-ID"
        with patch("jireh.runtime.telemetry.logger.info") as info:
            response = self.client.get(
                "/private/" + secret + "/?access_token=" + secret,
                HTTP_X_REQUEST_ID=secret,
            )
        self.assertEqual(response.status_code, 404)
        event = json.loads(info.call_args.args[0])
        self.assertEqual(event["route"], "closed_or_unmatched")
        self.assertEqual(event["status_code"], 404)
        self.assertNotIn(secret, info.call_args.args[0])
        self.assertNotIn("private", info.call_args.args[0])
        self.assertNotIn("access_token", info.call_args.args[0])

    @override_settings(
        ROOT_URLCONF="jireh.runtime.urls",
        MIDDLEWARE=["jireh.runtime.telemetry.RuntimeRequestCorrelationMiddleware"],
    )
    def test_readiness_database_failure_uses_fixed_event_without_exception_text(self):
        with patch(
            "jireh.runtime.urls.connection.cursor",
            side_effect=DatabaseError("private db hostname password USER"),
        ), patch("jireh.runtime.telemetry.logger.warning") as warning:
            response = self.client.get("/readyz/", HTTP_X_CORRELATION_ID="UNTRUSTED")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})
        event = json.loads(warning.call_args.args[0])
        self.assertEqual(event["route"], "database_readiness")
        self.assertEqual(event["event_type"], "database_readiness_failure")
        self.assertEqual(event["correlation_id"], response["X-Correlation-ID"])
        self.assertEqual(event["status_code"], 503)
        self.assertNotIn("private", warning.call_args.args[0])
        self.assertNotIn("password", warning.call_args.args[0])
        self.assertNotIn("UNTRUSTED", warning.call_args.args[0])

    @override_settings(
        ROOT_URLCONF="jireh.runtime.urls",
        MIDDLEWARE=["jireh.runtime.telemetry.RuntimeRequestCorrelationMiddleware"],
    )
    def test_post_is_still_disallowed_and_has_correlation(self):
        with patch("jireh.runtime.telemetry.logger.info") as info:
            response = self.client.post("/healthz/", data={"secret": "DO-NOT-LOG"})
        self.assertEqual(response.status_code, 405)
        self.assertEqual(json.loads(info.call_args.args[0])["status_code"], 405)
        self.assertNotIn("DO-NOT-LOG", info.call_args.args[0])
        self.assertIn("X-Correlation-ID", response)

    def test_unhandled_exception_is_logged_without_exception_text(self):
        factory = RequestFactory()
        request = factory.get("/private/sensitive-account/")
        middleware = RuntimeRequestCorrelationMiddleware(
            lambda _request: (_ for _ in ()).throw(ValueError("SECRET-ERROR"))
        )
        with patch("jireh.runtime.telemetry.logger.warning") as warning:
            with self.assertRaisesRegex(ValueError, "SECRET-ERROR"):
                middleware(request)
        event = json.loads(warning.call_args.args[0])
        self.assertEqual(event["status_code"], 500)
        self.assertEqual(event["route"], "closed_or_unmatched")
        self.assertNotIn("SECRET-ERROR", warning.call_args.args[0])

    def test_unusual_http_method_is_bounded_and_does_not_leak(self):
        factory = RequestFactory()
        request = factory.generic("SECRET-METHOD", "/private/SECRET-PATH/")
        middleware = RuntimeRequestCorrelationMiddleware(
            lambda _request: HttpResponse(status=405)
        )
        with patch("jireh.runtime.telemetry.logger.info") as info:
            response = middleware(request)
        self.assertEqual(response.status_code, 405)
        event = json.loads(info.call_args.args[0])
        self.assertEqual(event["method"], "OTHER")
        self.assertNotIn("SECRET", info.call_args.args[0])
