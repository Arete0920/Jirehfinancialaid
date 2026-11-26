"""Explicit in-memory/CI fixture scope; never a live financial-intake profile."""
import os
from uuid import UUID

from django.conf import settings
from django.db import connection

FINANCIAL_URLCONF = "jireh.runtime.customer_financial_portal_urls"
FINANCIAL_FLAGS = (
    "JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE",
    "JIREH_SYNTHETIC_DOCUMENTS_ONLY",
    "JIREH_SYNTHETIC_APPLICATION_REVIEW",
)
_TEST_SETTINGS = frozenset({"jireh.schools.test_settings", "jireh.schools.postgres_test_settings"})


def _disposable_database():
    database = connection.settings_dict
    name = str(database.get("NAME", ""))
    if connection.vendor == "sqlite":
        return name in (":memory:", "file:memorydb_default?mode=memory&cache=shared")
    return (
        connection.vendor == "postgresql"
        and os.environ.get("JIREH_POSTGRES_CI_ONLY") == "1"
        and database.get("HOST") == "127.0.0.1"
        and database.get("USER") == "jireh_ci"
        and name == "test_jireh_ci"
    )


def financial_profile_available():
    startup = os.environ.get("DJANGO_SETTINGS_MODULE")
    scopes = getattr(settings, "JIREH_FINANCIAL_FIXTURE_SCOPES", ())
    key = getattr(settings, "JIREH_SYNTHETIC_QUESTIONNAIRE_KEY", None)
    return (
        startup in _TEST_SETTINGS
        and getattr(settings, "SETTINGS_MODULE", None) in (None, startup)
        and settings.ROOT_URLCONF == FINANCIAL_URLCONF
        and getattr(settings, "JIREH_CUSTOMER_FINANCIAL_ACCEPTANCE", False) is True
        and getattr(settings, "JIREH_CUSTOMER_PORTAL_ACCEPTANCE", False) is True
        and getattr(settings, "JIREH_CUSTOMER_EXTERNAL_IDENTITY_ACCEPTANCE", False) is False
        and getattr(settings, "JIREH_CUSTOMER_WORKSPACE_ACCEPTANCE", False) is False
        and getattr(settings, "JIREH_SYNTHETIC_SUBMISSION_ONLY", False) is False
        and all(getattr(settings, flag, False) is True for flag in FINANCIAL_FLAGS)
        and type(key) is bytes and len(key) == 32
        and type(scopes) is tuple and 0 < len(scopes) <= 100
        and all(type(scope) is tuple and len(scope) == 3
                and all(type(identifier) is UUID and identifier.int != 0 for identifier in scope)
                for scope in scopes)
        and _disposable_database()
    )


def financial_scope_allowed(school_id, household_id, academic_year_id):
    return (financial_profile_available()
            and (school_id, household_id, academic_year_id) in settings.JIREH_FINANCIAL_FIXTURE_SCOPES)
