"""Routes: JSON under ``/api/``; every other path is the single-page terminal."""

from __future__ import annotations

from django.urls import path, re_path

from server.api import views

urlpatterns = [
    path("api/hyperliquid/backfill-jobs/", views.hyperliquid_backfill_jobs, name="hyperliquid_backfill_jobs"),
    path("api/markout-model/health/", views.markout_model_health, name="markout_model_health"),
    path("api/markout-model/decisions/", views.markout_fill_decisions, name="markout_fill_decisions"),
    re_path(r"^(?!api/|static/).*$", views.terminal, name="terminal"),
]
