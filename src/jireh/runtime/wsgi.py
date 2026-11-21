"""Standalone WSGI entry point; never permit test-settings overrides."""

import os

from django.core.wsgi import get_wsgi_application

os.environ["DJANGO_SETTINGS_MODULE"] = "jireh.runtime.settings"
application = get_wsgi_application()
