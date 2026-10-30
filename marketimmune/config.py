"""Repository paths, thresholds and date ranges, loaded from ``configs/*.yaml``.

Data lives under ``$MARKETIMMUNE_DATA`` (default: ``<repo>/data``) in the medallion
layout ``bronze/`` (raw downloads), ``silver/`` (parsed, typed Parquet) and
``gold/`` (analysis tables such as ``race_episodes.parquet``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from functools import cache
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
CONFIGS = REPO / "configs"
RESULTS = REPO / "eval"


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def bronze(self) -> Path:
        return self.root / "bronze"

    @property
    def silver(self) -> Path:
        return self.root / "silver"

    @property
    def gold(self) -> Path:
        return self.root / "gold"

    @property
    def logs(self) -> Path:
        return self.root / "logs"


def paths() -> Paths:
    return Paths(Path(os.environ.get("MARKETIMMUNE_DATA", REPO / "data")))


@cache
def load(name: str) -> dict[str, Any]:
    """Load ``configs/<name>.yaml`` (cached)."""
    with (CONFIGS / f"{name}.yaml").open() as fh:
        out: dict[str, Any] = yaml.safe_load(fh)
    return out


def days(start: date | str, end: date | str) -> list[date]:
    """Inclusive list of days."""
    s = date.fromisoformat(start) if isinstance(start, str) else start
    e = date.fromisoformat(end) if isinstance(end, str) else end
    if e < s:
        raise ValueError(f"end {e} before start {s}")
    return [s + timedelta(days=i) for i in range((e - s).days + 1)]


def window(name: str) -> list[date]:
    """Days of a named window in ``configs/data.yaml``; raises if still TBD."""
    w = load("data")["windows"][name]
    if w["start"] is None or w["end"] is None:
        raise ValueError(f"window {name!r} is TBD; set it from the G0 note first")
    return days(w["start"], w["end"])
