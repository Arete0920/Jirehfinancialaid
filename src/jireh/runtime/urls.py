"""Standalone runtime: non-sensitive liveness and database readiness only.

Neither route exposes family, staff, financial, test or buyer functionality.
Readiness demonstrates one database roundtrip, not a certified deployment.
"""

from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.urls import path
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe


@never_cache
@require_safe
def liveness(_request):
    """Process liveness only; not database, security or demo certification."""
    return JsonResponse({"status": "alive"})


@never_cache
@require_safe
def readiness(_request):
    """Fail closed when the configured database cannot complete SELECT 1.

    Do not return exception messages, hostnames, SQL errors or credentials.
    A successful query is connectivity evidence only: it does not establish
    schema parity, migrations, tenant isolation, security or release GO.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone() != (1,):
                return JsonResponse({"status": "unavailable"}, status=503)
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ready"})


urlpatterns = [
    path("healthz/", liveness, name="jireh_health"),
    path("readyz/", readiness, name="jireh_database_readiness"),
]
