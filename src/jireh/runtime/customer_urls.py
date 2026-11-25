"""Prepayment customer-core route candidate; not mounted by runtime.urls.

Reuse school-scoped domain handlers without importing test/demo routing or
fictional financial collection. Authentication must already be established by
an independently accepted identity provider or the separately gated family
password-session candidate. No activation here.
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

from .customer_family_sessions import (
    FAMILY_SESSION_KEY, family_session_eligible, family_login, family_logout,
)
from .customer_director_sessions import (
    DIRECTOR_SESSION_KEY, director_session_available, director_session_authorized,
    director_login, director_begin, director_complete, director_logout, disposable_identity_context,
)
from .customer_onboarding import (
    ONBOARDING_SESSION_KEY, onboarding_login, onboarding_logout, onboarding_redeem,
)

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


def customer_core_available(request):
    """Shared closed-by-default transport and session configuration gate."""
    return (
        getattr(settings, "JIREH_CUSTOMER_CORE_ACCEPTANCE", False) is True
        and settings.DEBUG is False and request.is_secure()
        and all(getattr(settings, name, False) is True for name in _REQUIRED)
        and all(getattr(settings, name, False) is False for name in _FORBIDDEN)
        and settings.SESSION_ENGINE == "django.contrib.sessions.backends.db"
    )


def customer_core_only(view, *, allow_family_session=True, session_endpoint=False,
                       onboarding_endpoint=False, director_endpoint=False, director_access=False):
    """Protect the explicit allowlist even if accidentally included elsewhere."""
    @never_cache
    @wraps(view)
    def guarded(request, *args, **kwargs):
        if not customer_core_available(request):
            response = JsonResponse({"detail": "Not found."}, status=404)
        elif (session_endpoint or onboarding_endpoint) and getattr(
            settings, "JIREH_CUSTOMER_FAMILY_SESSION_ACCEPTANCE", False
        ) is not True:
            response = JsonResponse({"detail": "Not found."}, status=404)
        elif onboarding_endpoint and getattr(settings, "JIREH_CUSTOMER_ONBOARDING_ACCEPTANCE", False) is not True:
            response = JsonResponse({"detail": "Not found."}, status=404)
        elif director_endpoint and not director_session_available(request):
            response = JsonResponse({"detail": "Not found."}, status=404)
        elif not (session_endpoint or onboarding_endpoint or director_endpoint) and (
            not getattr(getattr(request, "user", None), "is_authenticated", False) or not request.user.is_active
        ):
            response = JsonResponse({"detail": "Forbidden."}, status=403)
        else:
            try:
                if DIRECTOR_SESSION_KEY in request.session and not (director_endpoint or director_access):
                    raise PermissionDenied("Director session is school restricted.")
                if director_endpoint and (FAMILY_SESSION_KEY in request.session or ONBOARDING_SESSION_KEY in request.session):
                    raise PermissionDenied("Separate director authentication required.")
                fixture_only = (
                    getattr(settings, "JIREH_CUSTOMER_EXTERNAL_IDENTITY_ACCEPTANCE", False) is True
                    and getattr(settings, "JIREH_CUSTOMER_DIRECTOR_SESSION_ACCEPTANCE", False) is False
                    and disposable_identity_context()
                    and not any(key in request.session for key in (
                        DIRECTOR_SESSION_KEY, FAMILY_SESSION_KEY, ONBOARDING_SESSION_KEY,
                    ))
                )
                if director_access:
                    if not fixture_only and not director_session_authorized(request, kwargs["school_id"]):
                        raise PermissionDenied("Director authentication required.")
                elif not (session_endpoint or onboarding_endpoint or director_endpoint):
                    if not fixture_only and request.session.get(FAMILY_SESSION_KEY) is not True:
                        raise PermissionDenied("Family authentication required.")
                # Invitation-only password sessions are never customer sessions.
                # Even a concurrent grant change cannot upgrade that session.
                if not onboarding_endpoint and ONBOARDING_SESSION_KEY in request.session:
                    raise PermissionDenied("Invitation-only session.")
                # A family password session cannot become a director session, even
                # if grants change after sign-in. Recheck eligibility on each use.
                if not session_endpoint and FAMILY_SESSION_KEY in request.session and (
                    not allow_family_session
                    or getattr(settings, "JIREH_CUSTOMER_FAMILY_SESSION_ACCEPTANCE", False) is not True
                    or request.session[FAMILY_SESSION_KEY] is not True
                    or not family_session_eligible(request.user)
                ):
                    raise PermissionDenied("Family session unavailable.")
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

_DIRECTOR_AUTH = "api/v1/schools/<uuid:school_id>/director-session/"

urlpatterns = [
    path(_DIRECTOR_AUTH + "sign-in/", customer_core_only(director_login, director_endpoint=True),
         name="jireh_customer_director_login"),
    path(_DIRECTOR_AUTH + "begin/", customer_core_only(director_begin, director_endpoint=True),
         name="jireh_customer_director_begin"),
    path(_DIRECTOR_AUTH + "complete/", customer_core_only(director_complete, director_endpoint=True),
         name="jireh_customer_director_complete"),
    path(_DIRECTOR_AUTH + "sign-out/", customer_core_only(director_logout, director_endpoint=True),
         name="jireh_customer_director_logout"),
    path("api/v1/onboarding/sign-in/", customer_core_only(onboarding_login, onboarding_endpoint=True),
         name="jireh_customer_onboarding_login"),
    path("api/v1/onboarding/sign-out/", customer_core_only(onboarding_logout, onboarding_endpoint=True),
         name="jireh_customer_onboarding_logout"),
    path(_HOUSEHOLD + "onboarding/redeem/", customer_core_only(onboarding_redeem, onboarding_endpoint=True),
         name="jireh_customer_onboarding_redeem"),
    path("api/v1/session/sign-in/", customer_core_only(family_login, session_endpoint=True),
         name="jireh_customer_family_login"),
    path("api/v1/session/sign-out/", customer_core_only(family_logout, session_endpoint=True),
         name="jireh_customer_family_logout"),
    path("api/v1/session/csrf/", customer_core_only(customer_csrf), name="jireh_customer_csrf"),
    path(_HOUSEHOLD, customer_core_only(household_detail), name="jireh_customer_household"),
    path(_HOUSEHOLD + "students/", customer_core_only(household_students), name="jireh_customer_students"),
    path(_DRAFT, customer_core_only(family_annual_draft), name="jireh_customer_draft"),
    path(_DRAFT + "students/", customer_core_only(selected_students), name="jireh_customer_selected"),
    path(_DRAFT + "students/<uuid:student_id>/", customer_core_only(select_student), name="jireh_customer_select"),
    path(_DIRECTOR, customer_core_only(staff_application_index, allow_family_session=False, director_access=True), name="jireh_customer_cases"),
    path(_DIRECTOR + "<uuid:application_id>/", customer_core_only(staff_application_detail, allow_family_session=False, director_access=True), name="jireh_customer_case"),
]
