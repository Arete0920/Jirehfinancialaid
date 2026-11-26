"""Independent disposable operations readback profile; never a live route."""
from django.conf import settings

from .customer_director_sessions import disposable_identity_context
from .customer_financial_policy import _disposable_database

OPERATIONS_URLCONF = "jireh.runtime.operator_portal_urls"
_REQUIRED = (
    "JIREH_OPERATOR_PORTAL_ACCEPTANCE", "JIREH_OPERATOR_WEBAUTHN_CHALLENGES_ENABLED",
    "JIREH_SYNTHETIC_SETUP_INTENT_ONLY", "JIREH_SYNTHETIC_PREPARATION_JOB_ONLY",
    "JIREH_SYNTHETIC_PROVISIONING_ONLY", "JIREH_SCHOOL_SETUP_ACTION_MFA_ENABLED",
    "JIREH_OPERATOR_ACTION_MFA_ENABLED", "SESSION_COOKIE_SECURE",
    "SESSION_COOKIE_HTTPONLY", "CSRF_COOKIE_SECURE", "CSRF_COOKIE_HTTPONLY",
    "SECURE_SSL_REDIRECT",
)
_FORBIDDEN = (
    "JIREH_CUSTOMER_CORE_ACCEPTANCE", "JIREH_CUSTOMER_PORTAL_ACCEPTANCE",
    "JIREH_CUSTOMER_WORKSPACE_ACCEPTANCE", "JIREH_CUSTOMER_FINANCIAL_ACCEPTANCE",
    "JIREH_CUSTOMER_EXTERNAL_IDENTITY_ACCEPTANCE", "JIREH_CUSTOMER_FAMILY_SESSION_ACCEPTANCE",
    "JIREH_CUSTOMER_ONBOARDING_ACCEPTANCE", "JIREH_CUSTOMER_DIRECTOR_SESSION_ACCEPTANCE",
    "JIREH_SYNTHETIC_SUBMISSION_ONLY", "JIREH_SYNTHETIC_DOCUMENTS_ONLY",
    "JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE", "JIREH_SYNTHETIC_APPLICATION_REVIEW",
    "JIREH_FIRST_DIRECTOR_BOOTSTRAP_ENABLED", "JIREH_OPERATOR_CREDENTIAL_RECOVERY_ENABLED",
    "JIREH_EMAIL_DELIVERY_ENABLED",
)


def operations_profile_available():
    return (
        disposable_identity_context() and _disposable_database()
        and settings.ROOT_URLCONF == OPERATIONS_URLCONF
        and settings.DEBUG is False
        and settings.SESSION_ENGINE == "django.contrib.sessions.backends.db"
        and all(getattr(settings, flag, False) is True for flag in _REQUIRED)
        and all(getattr(settings, flag, False) is False for flag in _FORBIDDEN)
    )
