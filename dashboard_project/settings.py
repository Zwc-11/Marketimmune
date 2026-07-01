"""
Django settings for MarketImmune Dashboard
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-marketimmune-dev-key-change-in-production'

DEBUG = True

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'dashboard',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
]

ROOT_URLCONF = 'dashboard_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'dashboard', 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
    }
}

REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 100,
}

CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'dashboard', 'static'),
]

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Live market strip configuration. The React UI calls Django without choosing an
# instrument; change these in `.env` rather than editing frontend code.
MARKETIMMUNE_HYPERLIQUID_COIN = os.environ.get(
    'MARKETIMMUNE_HYPERLIQUID_COIN',
    'BTC',
).strip()
MARKETIMMUNE_HYPERLIQUID_BUDGET_MS = float(
    os.environ.get('MARKETIMMUNE_HYPERLIQUID_BUDGET_MS', '2000')
)
MARKETIMMUNE_HYPERLIQUID_CACHE_TTL_MS = float(
    os.environ.get('MARKETIMMUNE_HYPERLIQUID_CACHE_TTL_MS', '5000')
)
MARKETIMMUNE_HYPERLIQUID_CANDLE_INTERVAL = os.environ.get(
    'MARKETIMMUNE_HYPERLIQUID_CANDLE_INTERVAL',
    '1m',
).strip()
MARKETIMMUNE_HYPERLIQUID_CANDLE_LOOKBACK_MINUTES = int(
    os.environ.get('MARKETIMMUNE_HYPERLIQUID_CANDLE_LOOKBACK_MINUTES', '240')
)
MARKETIMMUNE_HYPERLIQUID_CANDLE_CACHE_TTL_MS = float(
    os.environ.get('MARKETIMMUNE_HYPERLIQUID_CANDLE_CACHE_TTL_MS', '30000')
)

# Promoted Hyperliquid CatBoost markout artifact served by the Models screen.
# These defaults point at the first real SOL panel trained from requester-pays
# archive data with 2026-06-01 held out. Override in `.env` when promoting a
# broader multi-asset artifact.
MARKETIMMUNE_PROMOTED_MARKOUT_MODEL_PATH = os.environ.get(
    'MARKETIMMUNE_PROMOTED_MARKOUT_MODEL_PATH',
    'data/models/hyperliquid_catboost_SOL_20260527_20260531_holdout_20260601_10s.cbm',
)
MARKETIMMUNE_PROMOTED_MARKOUT_CALIBRATOR_PATH = os.environ.get(
    'MARKETIMMUNE_PROMOTED_MARKOUT_CALIBRATOR_PATH',
    'data/models/hyperliquid_catboost_SOL_20260527_20260531_holdout_20260601_10s.isotonic.json',
)
MARKETIMMUNE_PROMOTED_MARKOUT_REPORT_PATH = os.environ.get(
    'MARKETIMMUNE_PROMOTED_MARKOUT_REPORT_PATH',
    'reports/hyperliquid_markout_SOL_20260527_20260531_holdout_20260601.json',
)
MARKETIMMUNE_PROMOTED_MARKOUT_GOLD_PATH = os.environ.get(
    'MARKETIMMUNE_PROMOTED_MARKOUT_GOLD_PATH',
    'data/hyperliquid/gold/hyperliquid/training/SOL/SOL-training-20260601.parquet',
)
MARKETIMMUNE_PROMOTED_MARKOUT_GOLD_ROOT = os.environ.get(
    'MARKETIMMUNE_PROMOTED_MARKOUT_GOLD_ROOT',
    'data/hyperliquid/gold/hyperliquid/training',
)
MARKETIMMUNE_PROMOTED_MARKOUT_GOLD_AUTO_DISCOVER = os.environ.get(
    'MARKETIMMUNE_PROMOTED_MARKOUT_GOLD_AUTO_DISCOVER',
    '1',
)
MARKETIMMUNE_MARKOUT_DECISION_LIMIT = int(
    os.environ.get('MARKETIMMUNE_MARKOUT_DECISION_LIMIT', '20')
)
MARKETIMMUNE_MARKOUT_DECISION_REFRESH_TTL_MS = float(
    os.environ.get('MARKETIMMUNE_MARKOUT_DECISION_REFRESH_TTL_MS', '30000')
)
MARKETIMMUNE_LOOP_MARKOUT_DECISION_LIMIT = int(
    os.environ.get('MARKETIMMUNE_LOOP_MARKOUT_DECISION_LIMIT', '5')
)
