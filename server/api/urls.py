"""Routes: the terminal at ``/`` and ``/terminal/``, JSON under ``/api/``."""

from __future__ import annotations

from django.urls import path, re_path

from server.api import views

urlpatterns = [
    path("api/hyperliquid/live/", views.hyperliquid_live_snapshot, name="hyperliquid_live"),
    path("api/hyperliquid/candles/", views.hyperliquid_candles, name="hyperliquid_candles"),
    path(
        "api/hyperliquid/backfill-jobs/",
        views.hyperliquid_backfill_jobs,
        name="hyperliquid_backfill_jobs",
    ),
    path("api/markout-model/health/", views.markout_model_health, name="markout_model_health"),
    path(
        "api/markout-model/decisions/",
        views.markout_fill_decisions,
        name="markout_fill_decisions",
    ),
    # Every other path is the single-page app; its router picks the screen.
    re_path(r"^(?!api/|admin/|static/).*$", views.TerminalView.as_view(), name="terminal"),
]
