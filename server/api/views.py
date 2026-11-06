"""JSON endpoints the terminal polls, and the terminal itself.

``HEAD`` on an endpoint answers 405 without doing the work; the terminal uses it as a cheap
is-the-server-up check.
"""

from __future__ import annotations

import hmac
from pathlib import Path

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_GET

from server.api.services.hyperliquid_backfill import recent_hyperliquid_backfill_jobs
from server.api.services.markout_decisions import recent_markout_fill_decisions
from server.api.services.markout_model import promoted_markout_model_health

BUNDLE = Path(__file__).resolve().parent / "static" / "terminal" / "index.html"
REFRESH_MODES = {"auto": None, "1": True, "0": False}


@require_GET
def terminal(request: HttpRequest) -> HttpResponse:
    """The built terminal (``npm run build:server``); Vite emits relative asset URLs."""
    html = BUNDLE.read_text(encoding="utf-8").replace('="./assets/', '="/static/terminal/assets/')
    return HttpResponse(html, content_type="text/html")


@require_GET
def hyperliquid_backfill_jobs(request: HttpRequest) -> JsonResponse:
    return JsonResponse(recent_hyperliquid_backfill_jobs(limit=int(request.GET.get("limit", 10))))


@require_GET
def markout_model_health(request: HttpRequest) -> JsonResponse:
    samples = max(1, min(1000, int(request.GET.get("samples", 128))))
    return JsonResponse(promoted_markout_model_health(samples=samples))


LOOPBACK = {"127.0.0.1", "::1"}


def may_write(request: HttpRequest) -> bool:
    """A scoring pass writes to the database: allowed from this machine, or with the token."""
    token = settings.MARKETIMMUNE_API_TOKEN
    if token and hmac.compare_digest(request.headers.get("X-MarketImmune-Token", ""), token):
        return True
    return request.META.get("REMOTE_ADDR") in LOOPBACK


@require_GET
def markout_fill_decisions(request: HttpRequest) -> JsonResponse:
    """``?limit=N`` rows; ``?refresh=1`` forces a scoring pass, ``0`` reads only, ``auto`` (default)
    scores when stale. A request that may not write (``may_write``) only reads."""
    limit = request.GET.get("limit")
    refresh = REFRESH_MODES[request.GET.get("refresh", "auto")]
    if not may_write(request):
        refresh = False
    payload = recent_markout_fill_decisions(limit=None if limit is None else int(limit), refresh=refresh)
    return JsonResponse(payload)
