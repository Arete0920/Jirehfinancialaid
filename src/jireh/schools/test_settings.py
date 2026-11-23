"""Disposable in-memory test settings only. Never use for a deployed service."""

SECRET_KEY = "test-only--no-real-sessions-or-credentials"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "jireh.schools",
    "jireh.financial_aid",
]
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]
ROOT_URLCONF = "jireh.schools.urls"
ALLOWED_HOSTS = ["testserver"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
TIME_ZONE = "UTC"
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Enables a fictional submission-receipt fixture in disposable test/demo settings only.
# The standalone runtime does not set this switch and exposes no such endpoint.
JIREH_SYNTHETIC_SUBMISSION_ONLY = True

# Disposable synthetic document lifecycle tests only; runtime never enables it.
JIREH_SYNTHETIC_DOCUMENTS_ONLY = True
