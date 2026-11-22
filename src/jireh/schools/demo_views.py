"""Local synthetic-only page and authenticated demo routing metadata."""

from pathlib import Path

from django.http import HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .demo_seed import (
    DEMO_PARENT,
    DEMO_DIRECTOR_A,
    DEMO_DIRECTOR_B,
    DEMO_SCHOOL_A_CODE,
    DEMO_SCHOOL_B_CODE,
)
from .models import AcademicYear, Household, School


@never_cache
@require_GET
def demo_page(request):
    template = Path(__file__).with_name("demo_page.html").read_text(encoding="utf-8")
    response = HttpResponse(template, content_type="text/html; charset=utf-8")
    response["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
        "connect-src 'self'; img-src 'self' data:; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Frame-Options"] = "DENY"
    return response


@never_cache
@require_GET
def demo_config(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Forbidden."}, status=403)
    if request.user.username not in (DEMO_PARENT, DEMO_DIRECTOR_A, DEMO_DIRECTOR_B):
        return JsonResponse({"detail": "Forbidden."}, status=403)

    a = School.objects.get(code=DEMO_SCHOOL_A_CODE)
    b = School.objects.get(code=DEMO_SCHOOL_B_CODE)
    ya = AcademicYear.objects.get(school=a, name="2026-27")
    yb = AcademicYear.objects.get(school=b, name="2026-27")
    ha = Household.objects.get(school=a, name="Sample Family")
    hb = Household.objects.get(school=b, name="Unrelated Family")
    return JsonResponse(
        {
            "persona": request.user.username,
            "school_a": {
                "id": str(a.pk),
                "year_id": str(ya.pk),
                "household_id": str(ha.pk),
                "name": a.name,
            },
            "school_b": {
                "id": str(b.pk),
                "year_id": str(yb.pk),
                "household_id": str(hb.pk),
                "name": b.name,
            },
        }
    )
