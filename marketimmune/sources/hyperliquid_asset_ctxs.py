"""Funding, open interest and basis from the archive's daily ``asset_ctxs/<YYYYMMDD>.csv.lz4``.

One row per asset per snapshot, header ``time,coin,funding,open_interest,prev_day_px,
day_ntl_vlm,premium,oracle_px,mark_px,mid_px,impact_bid_px,impact_ask_px``; ``time`` is ISO
8601 UTC (``2023-09-16T00:00:00Z``).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime

from marketimmune.sources.hyperliquid_l2_archive import BPS


def asset_ctxs_key(date: str) -> str:
    return f"asset_ctxs/{date}.csv.lz4"


@dataclass(frozen=True, slots=True)
class AssetCtx:
    """One asset's context at one archive timestamp."""

    coin: str
    funding: float
    open_interest: float
    oracle_px: float
    mark_px: float
    mid_px: float
    premium: float
    ts_ms: int

    @property
    def basis_bps(self) -> float:
        """Perp-oracle basis: ``(mark - oracle) / oracle * 1e4``."""
        assert self.oracle_px > 0.0, f"{self.coin=} {self.oracle_px=}"
        return (self.mark_px - self.oracle_px) / self.oracle_px * BPS


def parse_asset_ctxs_csv(text: str) -> list[AssetCtx]:
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        mark_px = float(row["mark_px"])
        time = datetime.fromisoformat(row["time"])
        assert time.tzinfo is not None, f"{row['time']=} has no time zone"
        out.append(
            AssetCtx(
                coin=row["coin"],
                funding=float(row["funding"]),
                open_interest=float(row["open_interest"]),
                oracle_px=float(row["oracle_px"]),
                mark_px=mark_px,
                # NOTE: mid_px and premium are empty for an asset without a two-sided book.
                mid_px=float(row["mid_px"] or mark_px),
                premium=float(row["premium"] or 0.0),
                ts_ms=int(time.timestamp() * 1000),
            )
        )
    return out
