#!/usr/bin/env python3
"""Local, disposable, loopback-only browser demo. Never run against live data."""

import os
import sys
import tempfile
from pathlib import Path


def main():
    expected_settings = "jireh.schools.demo_settings"
    current = os.environ.get("DJANGO_SETTINGS_MODULE")
    if current not in (None, expected_settings):
        raise SystemExit("Refusing demo: a different Django settings module is set.")
    if os.environ.get("JIREH_LOCAL_DEMO_DB"):
        raise SystemExit("Refusing demo: an existing demo database path was supplied.")
    if os.environ.get("JIREH_ENABLE_RUNTIME") == "1":
        raise SystemExit("Refusing demo: runtime activation is present in environment.")

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    with tempfile.TemporaryDirectory(prefix="jireh-synthetic-browser-") as temp:
        path = Path(temp, "disposable.sqlite3")
        os.environ["DJANGO_SETTINGS_MODULE"] = expected_settings
        os.environ["JIREH_LOCAL_DEMO_ONLY"] = "YES-SYNTHETIC-ONLY"
        os.environ["JIREH_LOCAL_DEMO_DB"] = str(path)

        import django
        from django.conf import settings
        from django.core.management import call_command

        django.setup()
        if settings.ROOT_URLCONF != "jireh.schools.demo_urls":
            raise SystemExit("Refusing demo: unsafe routing.")
        if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.sqlite3":
            raise SystemExit("Refusing demo: database engine must be SQLite.")
        if Path(settings.DATABASES["default"]["NAME"]) != path:
            raise SystemExit("Refusing demo: database path does not match temporary file.")
        if settings.ALLOWED_HOSTS != ["127.0.0.1", "localhost", "testserver"]:
            raise SystemExit("Refusing demo: unexpected allowed hosts.")

        call_command("migrate", interactive=False, verbosity=0)
        from jireh.schools.demo_seed import seed_synthetic_browser_demo

        seed_synthetic_browser_demo()
        print("\nJIREH — LOCAL SYNTHETIC BROWSER DEMONSTRATION", flush=True)
        print("Open http://127.0.0.1:8765/local-demo/", flush=True)
        print("Loopback-only. Fictional schools and users. Database removed on exit.", flush=True)
        print("No production routes, real family data, submission, awards or payment.", flush=True)
        print("Press Ctrl+C to shut down and remove the disposable database.\n", flush=True)
        try:
            call_command(
                "runserver",
                "127.0.0.1:8765",
                use_reloader=False,
                verbosity=0,
            )
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
