"""Django settings for the MarketImmune API and terminal.

Paths are relative to the repository root (``BASE_DIR``). Every
``MARKETIMMUNE_*`` value can be overridden from the environment.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "django-insecure-marketimmune-dev-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "server.api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "server.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 100,
}

CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


# Live Hyperliquid Info API.
MARKETIMMUNE_HYPERLIQUID_COIN = _env("MARKETIMMUNE_HYPERLIQUID_COIN", "SOL")
MARKETIMMUNE_HYPERLIQUID_BUDGET_MS = float(_env("MARKETIMMUNE_HYPERLIQUID_BUDGET_MS", "2000"))
MARKETIMMUNE_HYPERLIQUID_CACHE_TTL_MS = float(_env("MARKETIMMUNE_HYPERLIQUID_CACHE_TTL_MS", "5000"))
MARKETIMMUNE_HYPERLIQUID_CANDLE_INTERVAL = _env("MARKETIMMUNE_HYPERLIQUID_CANDLE_INTERVAL", "1m")
MARKETIMMUNE_HYPERLIQUID_CANDLE_LOOKBACK_MINUTES = int(
    _env("MARKETIMMUNE_HYPERLIQUID_CANDLE_LOOKBACK_MINUTES", "240")
)
MARKETIMMUNE_HYPERLIQUID_CANDLE_CACHE_TTL_MS = float(
    _env("MARKETIMMUNE_HYPERLIQUID_CANDLE_CACHE_TTL_MS", "30000")
)

# Promoted markout model and the Gold partitions it scores.
_MODEL_STEM = "data/models/hyperliquid_catboost_SOL_20260527_20260531_holdout_20260601_10s"
MARKETIMMUNE_PROMOTED_MARKOUT_MODEL_PATH = _env(
    "MARKETIMMUNE_PROMOTED_MARKOUT_MODEL_PATH", f"{_MODEL_STEM}.cbm"
)
MARKETIMMUNE_PROMOTED_MARKOUT_CALIBRATOR_PATH = _env(
    "MARKETIMMUNE_PROMOTED_MARKOUT_CALIBRATOR_PATH", f"{_MODEL_STEM}.isotonic.json"
)
MARKETIMMUNE_PROMOTED_MARKOUT_REPORT_PATH = _env(
    "MARKETIMMUNE_PROMOTED_MARKOUT_REPORT_PATH",
    "eval/markout_sol_10s/hyperliquid_markout_SOL_20260527_20260531_holdout_20260601.json",
)
MARKETIMMUNE_PROMOTED_MARKOUT_GOLD_PATH = _env(
    "MARKETIMMUNE_PROMOTED_MARKOUT_GOLD_PATH",
    "data/gold/hyperliquid/training/SOL/SOL-training-20260601.parquet",
)
MARKETIMMUNE_PROMOTED_MARKOUT_GOLD_ROOT = _env(
    "MARKETIMMUNE_PROMOTED_MARKOUT_GOLD_ROOT", "data/gold/hyperliquid/training"
)
MARKETIMMUNE_PROMOTED_MARKOUT_GOLD_AUTO_DISCOVER = _env(
    "MARKETIMMUNE_PROMOTED_MARKOUT_GOLD_AUTO_DISCOVER", "1"
)
MARKETIMMUNE_MARKOUT_DECISION_LIMIT = int(_env("MARKETIMMUNE_MARKOUT_DECISION_LIMIT", "20"))
MARKETIMMUNE_MARKOUT_DECISION_REFRESH_TTL_MS = float(
    _env("MARKETIMMUNE_MARKOUT_DECISION_REFRESH_TTL_MS", "30000")
)
