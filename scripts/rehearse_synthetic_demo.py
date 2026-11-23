#!/usr/bin/env python3
"""Run Jireh's synthetic household onboarding and draft walkthrough rehearsals.

This executes tests, not a production service or browser UI. It never
runs migrations against a configured deployment or enables customer routes.
"""

import os
import sys
from pathlib import Path


TEST_SETTINGS = "jireh.schools.test_settings"


def main():
    configured = os.environ.get("DJANGO_SETTINGS_MODULE")
    if configured not in (None, TEST_SETTINGS):
        raise SystemExit(
            "Refusing demo: DJANGO_SETTINGS_MODULE must be unset "
            "or jireh.schools.test_settings."
        )

    os.environ["DJANGO_SETTINGS_MODULE"] = TEST_SETTINGS
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "src"))

    import django
    from django.conf import settings
    from django.core.management import call_command

    django.setup()
    if settings.ROOT_URLCONF != "jireh.schools.urls":
        raise SystemExit("Refusing demo: unexpected test-only URL routing.")
    if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.sqlite3":
        raise SystemExit("Refusing demo: demo runner requires disposable SQLite tests.")
    if settings.DATABASES["default"]["NAME"] != ":memory:":
        raise SystemExit("Refusing demo: demo runner requires in-memory database.")

    print("JIREH SYNTHETIC DEMO REHEARSAL — NOT A CUSTOMER APPLICATION")
    print("Fictional schools, families and draft records. Invitation mail stays in memory.")
    print("No production routes, financial data, payment, or live accounts are used.")
    call_command(
        "test",
        "jireh.financial_aid.test_demo_walkthrough",
        "jireh.schools.test_onboarding_rehearsal",
        verbosity=2,
        interactive=False,
    )


if __name__ == "__main__":
    main()
