"""API views for promoted markout model artifacts."""

from __future__ import annotations

from rest_framework.decorators import api_view
from rest_framework.response import Response

from dashboard.services.markout_decision_service import recent_markout_fill_decisions
from dashboard.services.markout_model_service import promoted_markout_model_health


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
