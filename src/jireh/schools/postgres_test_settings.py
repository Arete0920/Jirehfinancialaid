"""DISPOSABLE CI TESTS ONLY. Never use with customer or nonlocal databases.

The strict environment guard and fixed localhost/test-only credentials
prevent the test suite from accidentally touching a remote PostgreSQL server.
"""

import os

from django.core.exceptions import ImproperlyConfigured

if os.environ.get("JIREH_POSTGRES_CI_ONLY") != "1":
    raise ImproperlyConfigured(
        "JIREH_POSTGRES_CI_ONLY=1 is required for disposable PostgreSQL tests."
    )

_ci_password = os.environ.get("JIREH_POSTGRES_CI_PASSWORD")
if not _ci_password or not _ci_password.startswith("ci-"):
    raise ImproperlyConfigured("A disposable CI database password is required.")

from .test_settings import *  # noqa: F403,F401

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "jireh_ci",
        "USER": "jireh_ci",
        "PASSWORD": _ci_password,
        "HOST": "127.0.0.1",
        "PORT": "5432",
        "CONN_MAX_AGE": 0,
        "TEST": {"NAME": "test_jireh_ci"},
    }
}
