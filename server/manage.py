#!/usr/bin/env python
"""Django's command-line utility; reads ``.env`` at the repository root first."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from django.core.management import execute_from_command_line
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parent.parent

if __name__ == "__main__":
    load_dotenv(REPO / ".env", override=False)
    sys.path.insert(0, str(REPO))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.settings")
    execute_from_command_line(sys.argv)
