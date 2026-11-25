"""Prepayment customer-core route candidate; not mounted by runtime.urls.

Reuse school-scoped domain handlers without importing test/demo routing or
fictional financial collection. Authentication must already be established by
an independently accepted identity provider. No login or activation here.
"""
from functools import wraps

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.http import Http404, JsonResponse
from django.middleware.csrf import get_token
from django.urls import path
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from jireh.financial_aid.family_views import family_annual_draft
from jireh.financial_aid.student_views import selected_students, select_student
from jireh.financial_aid.views import staff_application_detail, staff_application_index
from jireh.schools.views import household_detail, household_students


# A separate owner-approved runtime profile must opt in later; ordinary
# production settings must not import or enable this candidate.
_REQUIRED = (
    "SESSION_COOKIE_SECURE", "SESSION_COOKIE_HTTPONLY", "CSRF_COOKIE_SECURE",
    "CSRF_COOKIE_HTTPONLY", "SECURE_SSL_REDIRECT",
)
_FORBIDDEN = (
    "JIREH_CUSTOMER_WORKSPACE_ACCEPTANCE", "JIREH_SYNTHETIC_SUBMISSION_ONLY",
    "JIREH_SYNTHETIC_DOCUMENTS_ONLY", "JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE",
    "JIREH_SYNTHETIC_APPLICATION_REVIEW", "JIREH_OPERATOR_CREDENTIAL_RECOVERY_ENABLED",
)


def customer_core_only(view):
    """Protect the explicit allowlist even if accidentally included elsewhere."""
    @never_cache
    @wraps(view)
    def guarded(request, *args, **kwargs):
        if (getattr(settings, "JIREH_CUSTOMER_CORE_ACCEPTANCE", False) is not True
                or settings.DEBUG is not False or not request.is_secure()
                or any(getattr(settings, name, False) is not True for name in _REQUIRED)
                or any(getattr(settings, name, False) is not False for name in _FORBIDDEN)
                or settings.SESSION_ENGINE != "django.contrib.sessions.backends.db"):
            response = JsonResponse({"detail": "Not found."}, status=404)
        elif not getattr(getattr(request, "user", None), "is_authenticated", False) or not request.user.is_active:
            response = JsonResponse({"detail": "Forbidden."}, status=403)
        else:
            try:
                response = view(request, *args, **kwargs)
            except PermissionDenied:
                response = JsonResponse({"detail": "Forbidden."}, status=403)
            except Http404:
                response = JsonResponse({"detail": "Not found."}, status=404)
            except DatabaseError:
                response = JsonResponse({"detail": "Service unavailable."}, status=503)
        response["X-Content-Type-Options"] = "nosniff"
        response["X-Frame-Options"] = "DENY"
        response["Referrer-Policy"] = "no-referrer"
        response["X-Robots-Tag"] = "noindex, nofollow"
        return response
    return guarded


@require_GET
def customer_csrf(request):
    """Supply a masked token to an authenticated same-origin browser client."""
    return JsonResponse({"csrf_token": get_token(request)})


_HOUSEHOLD = "api/v1/schools/<uuid:school_id>/households/<uuid:household_id>/"
_DRAFT = _HOUSEHOLD + "academic-years/<uuid:academic_year_id>/aid-application/draft/"
_DIRECTOR = "api/v1/schools/<uuid:school_id>/academic-years/<uuid:academic_year_id>/aid-applications/"

urlpatterns = [
    path("api/v1/session/csrf/", customer_core_only(customer_csrf), name="jireh_customer_csrf"),
    path(_HOUSEHOLD, customer_core_only(household_detail), name="jireh_customer_household"),
    path(_HOUSEHOLD + "students/", customer_core_only(household_students), name="jireh_customer_students"),
    path(_DRAFT, customer_core_only(family_annual_draft), name="jireh_customer_draft"),
    path(_DRAFT + "students/", customer_core_only(selected_students), name="jireh_customer_selected"),
    path(_DRAFT + "students/<uuid:student_id>/", customer_core_only(select_student), name="jireh_customer_select"),
    path(_DIRECTOR, customer_core_only(staff_application_index), name="jireh_customer_cases"),
    path(_DIRECTOR + "<uuid:application_id>/", customer_core_only(staff_application_detail), name="jireh_customer_case"),
]
