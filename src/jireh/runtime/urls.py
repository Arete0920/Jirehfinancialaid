"""Standalone runtime routes: liveness only, not test or buyer APIs."""

from django.http import JsonResponse
from django.urls import path
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe


@never_cache
@require_safe
def liveness(_request):
    """Process liveness only; not database, security or demo certification."""
    return JsonResponse({"status": "alive"})


urlpatterns = [path("healthz/", liveness, name="jireh_health")]
