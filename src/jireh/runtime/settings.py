"""Standalone, closed-by-default Django settings. NOT certified for deployment.

The only exposed route is a non-sensitive liveness probe. Family and staff
handlers remain in disposable test settings until authentication, grant
provisioning, CSRF/session policy, and end-to-end authorization are accepted.
"""

from .config import read_runtime_config

_cfg = read_runtime_config()

SECRET_KEY = _cfg.secret_key
SECRET_KEY_FALLBACKS = []
DEBUG = False
ALLOWED_HOSTS = list(_cfg.allowed_hosts)
CSRF_TRUSTED_ORIGINS = []

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "jireh.schools.apps.SchoolsConfig",
    "jireh.financial_aid.apps.FinancialAidConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "jireh.runtime.telemetry.RuntimeRequestCorrelationMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "runtime_request": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "runtime_json",
        },
    },
    "formatters": {
        "runtime_json": {"format": "%(message)s"},
    },
    "loggers": {
        "jireh.runtime.request": {
            "handlers": ["runtime_request"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

ROOT_URLCONF = "jireh.runtime.urls"
WSGI_APPLICATION = "jireh.runtime.wsgi.application"
ASGI_APPLICATION = "jireh.runtime.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _cfg.db_name,
        "USER": _cfg.db_user,
        "PASSWORD": _cfg.db_password,
        "HOST": _cfg.db_host,
        "PORT": str(_cfg.db_port),
        "CONN_MAX_AGE": 0,
        "OPTIONS": {"sslmode": "verify-full", "sslrootcert": _cfg.db_sslrootcert},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SECURE_SSL_REDIRECT = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_HSTS_SECONDS = 0  # Enable only after a verified HTTPS deployment.
SESSION_COOKIE_NAME = "jireh_session"
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
CSRF_COOKIE_NAME = "jireh_csrf"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
