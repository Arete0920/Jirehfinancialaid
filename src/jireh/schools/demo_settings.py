"""Disposable, loopback-only synthetic browser demonstration settings.

This module must never be used for hosted services or real-person data.
"""
import os
import secrets
from pathlib import Path

if os.environ.get("JIREH_LOCAL_DEMO_ONLY") != "YES-SYNTHETIC-ONLY":
    raise RuntimeError("Synthetic browser demo must be explicitly enabled by its local runner.")

_db = os.environ.get("JIREH_LOCAL_DEMO_DB", "")
if not _db or not Path(_db).is_absolute():
    raise RuntimeError("Synthetic browser demo requires an absolute disposable database path.")

from .test_settings import *  # noqa: F403,F401 (test-only baseline)

ROOT_URLCONF = "jireh.schools.demo_urls"
JIREH_CUSTOMER_WORKSPACE_ACCEPTANCE = True
# Ephemeral key lives only for this disposable, loopback-only demo process.
JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE = True
JIREH_SYNTHETIC_QUESTIONNAIRE_KEY = secrets.token_bytes(32)
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
DATABASES = {
    "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": _db},
}
DEBUG = False
# Inherits Django test-only defaults; this is loopback HTTP, not production.
CSRF_COOKIE_HTTPONLY = False  # local demo JS sends standard Django CSRF header
SESSION_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SAMESITE = "Strict"

# HTML is rendered through Django's autoescaping template engine.
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {},
    }
]
