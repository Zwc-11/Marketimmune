"""Django settings for the MarketImmune API and terminal.

Paths are relative to the repository root (``BASE_DIR``); every ``MARKETIMMUNE_*`` value
can be overridden from the environment.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "django-insecure-marketimmune-dev-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = ["django.contrib.staticfiles", "server.api"]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "django.middleware.common.CommonMiddleware"]
ROOT_URLCONF = "server.api.urls"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"

# Promoted markout model and the Gold partitions it scores (the newest one in the directory).
_MODEL_STEM = "data/models/hyperliquid_catboost_SOL_20260527_20260531_holdout_20260601_10s"
MARKETIMMUNE_PROMOTED_MARKOUT_MODEL_PATH = os.environ.get("MARKETIMMUNE_PROMOTED_MARKOUT_MODEL_PATH", f"{_MODEL_STEM}.cbm")
MARKETIMMUNE_PROMOTED_MARKOUT_CALIBRATOR_PATH = os.environ.get(
    "MARKETIMMUNE_PROMOTED_MARKOUT_CALIBRATOR_PATH", f"{_MODEL_STEM}.isotonic.json"
)
MARKETIMMUNE_PROMOTED_MARKOUT_REPORT_PATH = os.environ.get(
    "MARKETIMMUNE_PROMOTED_MARKOUT_REPORT_PATH",
    "eval/markout_sol_10s/hyperliquid_markout_SOL_20260527_20260531_holdout_20260601.json",
)
MARKETIMMUNE_PROMOTED_MARKOUT_GOLD_ROOT = os.environ.get("MARKETIMMUNE_PROMOTED_MARKOUT_GOLD_ROOT", "data/gold/hyperliquid/training/SOL")
MARKETIMMUNE_MARKOUT_DECISION_LIMIT = int(os.environ.get("MARKETIMMUNE_MARKOUT_DECISION_LIMIT", "20"))
MARKETIMMUNE_MARKOUT_DECISION_REFRESH_TTL_MS = float(os.environ.get("MARKETIMMUNE_MARKOUT_DECISION_REFRESH_TTL_MS", "30000"))
