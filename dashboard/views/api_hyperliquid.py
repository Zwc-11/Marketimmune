"""Live Hyperliquid public API endpoints."""

from __future__ import annotations

import httpx
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from dashboard.services.hyperliquid_service import (
    live_hyperliquid_candles,
    live_hyperliquid_snapshot,
)


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
