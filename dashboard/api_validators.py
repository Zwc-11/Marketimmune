"""Shared request validation helpers for dashboard JSON APIs."""
from __future__ import annotations

import re
from typing import Any

from marketimmune.simulator import ScenarioRegistry

VALID_LOOP_DIFFICULTIES = frozenset({"easy", "medium", "hard"})
VALID_SIMULATOR_SCENARIOS = frozenset(ScenarioRegistry.names())
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_loop_run_request(data: Any) -> tuple[str, int] | tuple[None, dict[str, str]]:
    """Validate POST body for ``trigger_immune_loop``."""
    if not isinstance(data, dict):
        return None, {"error": "Request body must be a JSON object.", "code": "invalid_body"}

    difficulty = str(data.get("difficulty", "medium")).strip().lower()
    if difficulty not in VALID_LOOP_DIFFICULTIES:
        return None, {
            "error": f"difficulty must be one of {', '.join(sorted(VALID_LOOP_DIFFICULTIES))}.",
            "code": "invalid_difficulty",
        }

    raw_limit = data.get("limit", 30)
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return None, {"error": "limit must be an integer.", "code": "invalid_limit"}

    if not 1 <= limit <= 500:
        return None, {"error": "limit must be between 1 and 500.", "code": "invalid_limit"}

    return (difficulty, limit), {}


def parse_simulator_control_request(
    payload: Any,
) -> tuple[dict[str, Any], dict[str, str]] | tuple[None, dict[str, str]]:
    """Validate POST/GET payload for ``control_replay``."""
    if not isinstance(payload, dict):
        return None, {"error": "Request body must be a JSON object.", "code": "invalid_body"}

    scenario = str(payload.get("scenario", "spoofing_layering")).strip()
    if scenario not in VALID_SIMULATOR_SCENARIOS:
        known = ", ".join(sorted(VALID_SIMULATOR_SCENARIOS))
        return None, {
            "error": f"scenario must be one of: {known}.",
            "code": "invalid_scenario",
        }

    symbol = str(payload.get("symbol", "BTCUSDT")).strip().upper()
    if not symbol or len(symbol) > 32:
        return None, {"error": "symbol must be 1–32 characters.", "code": "invalid_symbol"}

    raw_limit = payload.get("limit", 1440)
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return None, {"error": "limit must be an integer.", "code": "invalid_limit"}
    if not 1 <= limit <= 10_000:
        return None, {"error": "limit must be between 1 and 10000.", "code": "invalid_limit"}

    raw_speed = payload.get("speed", 10)
    try:
        speed = int(raw_speed)
    except (TypeError, ValueError):
        return None, {"error": "speed must be an integer.", "code": "invalid_speed"}
    if not 1 <= speed <= 100:
        return None, {"error": "speed must be between 1 and 100.", "code": "invalid_speed"}

    replay_date = payload.get("date")
    if replay_date is not None and replay_date != "":
        replay_date = str(replay_date).strip()
        if not _ISO_DATE.match(replay_date):
            return None, {
                "error": "date must be ISO format YYYY-MM-DD when provided.",
                "code": "invalid_date",
            }
    else:
        replay_date = None

    return (
        {
            "scenario": scenario,
            "symbol": symbol,
            "limit": limit,
            "speed": speed,
            "replay_date": replay_date,
        },
        {},
    )
