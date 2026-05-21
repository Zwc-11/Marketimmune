#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main() -> None:
    # Auto-load .env so ANTHROPIC_API_KEY / MARKETIMMUNE_USE_LLM /
    # CLAUDE_MODEL are available to every `manage.py` subcommand and
    # to the runserver process. `.env` is gitignored.
    try:
        from dotenv import load_dotenv  # noqa: WPS433 — optional dep.

        load_dotenv(override=False)
    except ImportError:
        pass

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard_project.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
