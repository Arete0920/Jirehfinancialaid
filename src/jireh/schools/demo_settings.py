"""Disposable, loopback-only synthetic browser demonstration settings.

This module must never be used for hosted services or real-person data.
"""
import os
from pathlib import Path

if os.environ.get("JIREH_LOCAL_DEMO_ONLY") != "YES-SYNTHETIC-ONLY":
    raise RuntimeError("Synthetic browser demo must be explicitly enabled by its local runner.")

_db = os.environ.get("JIREH_LOCAL_DEMO_DB", "")
if not _db or not Path(_db).is_absolute():
    raise RuntimeError("Synthetic browser demo requires an absolute disposable database path.")

from .test_settings import *  # noqa: F403,F401 (test-only baseline)

ROOT_URLCONF = "jireh.schools.demo_urls"
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
DATABASES = {
    "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": _db},
}
DEBUG = False
SESSION_COOKIE_SECURE = False  # localhost HTTP only, never real user sessions
CSRF_COOKIE_SECURE = False  # localhost HTTP only, never real user sessions
CSRF_COOKIE_HTTPONLY = False  # local demo JS sends standard Django CSRF header
SESSION_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SAMESITE = "Strict"
