"""Standalone ASGI entry point; never permit test-settings overrides."""

import os

from django.core.asgi import get_asgi_application

os.environ["DJANGO_SETTINGS_MODULE"] = "jireh.runtime.settings"
application = get_asgi_application()
