"""Run the Django server with E2E stubs installed."""

import os
import sys

os.environ["DJANGO_SETTINGS_MODULE"] = "application_manager.settings_e2e"

import django  # noqa: E402

django.setup()

if os.getenv("E2E_STUBS") == "1":
    from application_manager.e2e_stubs import install

    install()

from django.core.management import execute_from_command_line  # noqa: E402

execute_from_command_line([sys.argv[0], "runserver", "127.0.0.1:8099", "--noreload"])
