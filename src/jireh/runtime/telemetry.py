"""Privacy-minimized HTTP correlation for the closed standalone runtime.

Adapted from CROWN's request-correlation *concept*, not its caller-supplied
header or tenant/actor logging. Does not establish alert delivery, logging
retention, an incident-response service or production M1 acceptance.
"""

import json
import logging
import time
from datetime import datetime, timezone
from uuid import uuid4


logger = logging.getLogger("jireh.runtime.request")


def _route_class(path_info: object) -> str:
    """Never log raw paths: future customer URLs could contain sensitive IDs."""
    if path_info == "/healthz/":
        return "process_liveness"
    if path_info == "/readyz/":
        return "database_readiness"
    return "closed_or_unmatched"


class RuntimeRequestCorrelationMiddleware:
    """Generate an unspoofable per-request identifier and minimal event.

    Inbound correlation headers are intentionally ignored. A user-supplied
    identifier must not contaminate audit evidence or structured logs.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def _emit(self, request, *, correlation_id, started, status_code):
        route = _route_class(getattr(request, "path_info", None))
        event = {
            "event_type": (
                "database_readiness_failure"
                if route == "database_readiness" and status_code >= 500
                else "runtime_http"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "correlation_id": correlation_id,
            "route": route,
            "method": (
                request.method
                if request.method in ("GET", "HEAD", "POST", "OPTIONS")
                else "OTHER"
            ),
            "status_code": status_code,
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
        }
        message = json.dumps(event, sort_keys=True, separators=(",", ":"))
        if status_code >= 500:
            logger.warning(message)
        else:
            logger.info(message)

    def __call__(self, request):
        correlation_id = str(uuid4())
        request.jireh_correlation_id = correlation_id
        started = time.monotonic()
        try:
            response = self.get_response(request)
        except Exception:
            # Django usually converts handler exceptions to 500 responses.
            # Never emit the exception text, request data or user identifiers.
            self._emit(
                request, correlation_id=correlation_id,
                started=started, status_code=500,
            )
            raise
        response["X-Correlation-ID"] = correlation_id
        self._emit(
            request, correlation_id=correlation_id,
            started=started, status_code=response.status_code,
        )
        return response
