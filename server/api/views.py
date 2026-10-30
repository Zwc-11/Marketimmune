"""HTTP endpoints for the terminal: live Hyperliquid data, backfill jobs, model decisions.

``TerminalView`` serves the prebuilt React bundle (``frontend/`` -> ``static/terminal``).
Every other view returns JSON through Django REST framework.
"""

from __future__ import annotations

from pathlib import Path

import httpx
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.views import View
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from server.api.services.hyperliquid_backfill import recent_hyperliquid_backfill_jobs
from server.api.services.hyperliquid_live import (
    live_hyperliquid_candles,
    live_hyperliquid_snapshot,
)
from server.api.services.markout_decisions import recent_markout_fill_decisions
from server.api.services.markout_model import promoted_markout_model_health

BUNDLE = Path(__file__).resolve().parent / "static" / "terminal" / "index.html"


class TerminalView(View):
    """Serve the built terminal; Vite emits relative asset URLs, Django serves them."""

    def get(self, request: HttpRequest) -> HttpResponse:
        if not BUNDLE.exists():
            return HttpResponse(
                "<h1>Terminal bundle missing</h1>"
                "<pre>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</pre>",
                status=503,
                content_type="text/html",
            )
        html = BUNDLE.read_text(encoding="utf-8")
        html = html.replace('="./assets/', '="/static/terminal/assets/')
        return HttpResponse(html, content_type="text/html")


@api_view(["GET"])
def hyperliquid_live_snapshot(request):
    """Return a live/current Hyperliquid public Info API snapshot."""
    try:
        coin = str(request.query_params.get("coin") or settings.MARKETIMMUNE_HYPERLIQUID_COIN)
        budget_ms = float(
            request.query_params.get("budget_ms") or settings.MARKETIMMUNE_HYPERLIQUID_BUDGET_MS
        )
        timeout_s = max(budget_ms / 1000.0, 0.001)
        return Response(
            live_hyperliquid_snapshot(
                coin=coin,
                cache_ttl_ms=settings.MARKETIMMUNE_HYPERLIQUID_CACHE_TTL_MS,
                timeout_s=timeout_s,
            )
        )
    except ValueError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except httpx.HTTPError as exc:
        return Response(
            {
                "error": "Hyperliquid public API unavailable",
                "detail": str(exc),
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@api_view(["GET"])
def hyperliquid_candles(request):
    """Return recent Hyperliquid public Info API candles."""
    try:
        coin = str(request.query_params.get("coin") or settings.MARKETIMMUNE_HYPERLIQUID_COIN)
        budget_ms = float(
            request.query_params.get("budget_ms") or settings.MARKETIMMUNE_HYPERLIQUID_BUDGET_MS
        )
        interval = str(
            request.query_params.get("interval")
            or settings.MARKETIMMUNE_HYPERLIQUID_CANDLE_INTERVAL
        )
        lookback_minutes = int(
            request.query_params.get("lookback_minutes")
            or settings.MARKETIMMUNE_HYPERLIQUID_CANDLE_LOOKBACK_MINUTES
        )
        timeout_s = max(budget_ms / 1000.0, 0.001)
        return Response(
            live_hyperliquid_candles(
                coin=coin,
                interval=interval,
                lookback_minutes=lookback_minutes,
                cache_ttl_ms=settings.MARKETIMMUNE_HYPERLIQUID_CANDLE_CACHE_TTL_MS,
                timeout_s=timeout_s,
            )
        )
    except ValueError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except httpx.HTTPError as exc:
        return Response(
            {
                "error": "Hyperliquid candle API unavailable",
                "detail": str(exc),
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@api_view(["GET"])
def hyperliquid_backfill_jobs(request):
    """Return recent requester-pays backfill job statuses."""
    raw_limit = request.GET.get("limit", "10")
    try:
        limit = int(raw_limit)
    except ValueError:
        limit = 10
    return Response(recent_hyperliquid_backfill_jobs(limit=limit))


@api_view(["GET"])
def markout_model_health(request):
    """Return promoted Hyperliquid markout model health and benchmark evidence."""
    raw_samples = request.GET.get("samples", "128")
    try:
        samples = max(1, min(1000, int(raw_samples)))
    except ValueError:
        samples = 128
    return Response(promoted_markout_model_health(samples=samples))


@api_view(["GET"])
def markout_fill_decisions(request):
    """Return recent persisted promoted-model fill decisions."""
    raw_limit = request.GET.get("limit")
    try:
        limit = int(raw_limit) if raw_limit is not None else None
    except ValueError:
        limit = None
    return Response(
        recent_markout_fill_decisions(
            limit=limit,
            refresh=_refresh_mode(request.GET.get("refresh")),
        )
    )


def _refresh_mode(value: str | None) -> bool | None:
    if value is None or value.strip().lower() == "auto":
        return None
    return value.strip().lower() in {"1", "true", "yes", "force"}
