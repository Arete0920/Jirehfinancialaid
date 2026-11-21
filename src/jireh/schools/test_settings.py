"""Disposable in-memory test settings only. Never use for a deployed service."""

SECRET_KEY = "test-only--no-real-sessions-or-credentials"
INSTALLED_APPS = ["jireh.schools"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
TIME_ZONE = "UTC"
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
