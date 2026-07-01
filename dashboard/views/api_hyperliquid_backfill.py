"""Read-only API for persisted Hyperliquid backfill jobs."""

from __future__ import annotations

from rest_framework.decorators import api_view
from rest_framework.response import Response

from dashboard.services.hyperliquid_backfill_service import recent_hyperliquid_backfill_jobs


@api_view(["GET"])
def hyperliquid_backfill_jobs(request):
    """Return recent requester-pays backfill job statuses."""
    raw_limit = request.GET.get("limit", "10")
    try:
        limit = int(raw_limit)
    except ValueError:
        limit = 10
    return Response(recent_hyperliquid_backfill_jobs(limit=limit))
