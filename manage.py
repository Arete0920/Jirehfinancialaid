#!/usr/bin/env python3
"""Manage the standalone Jireh runtime, never disposable test settings."""

import os
from pathlib import Path
import sys


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
    os.environ["DJANGO_SETTINGS_MODULE"] = "jireh.runtime.settings"
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
