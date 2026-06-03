"""Shared view helpers used across the dashboard views package."""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings


def load_benchmark_report() -> dict:
    """Load the gradient-boosting risk-head benchmark report.

    Returns an empty dict when the artifact has not been produced yet;
    the template handles the "untrained" UI gracefully.
    """
    path = Path(settings.BASE_DIR) / "reports" / "risk_head_benchmark.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — bad JSON shouldn't break the dashboard.
        return {}
