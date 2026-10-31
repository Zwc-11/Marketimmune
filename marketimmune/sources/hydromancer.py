"""Hydromancer Reservoir: daily snapshots of every open Hyperliquid perp position (requester pays).

``s3://hydromancer-reservoir/global/snapshots/perp/all/date=YYYY-MM-DD/{block}_{timestamp_ms}.parquet``
(ap-northeast-1) holds one ABCI state per UTC date, which is not necessarily the day's last. It
starts in July 2025, with no captures from 2025-10-25 to 2025-12-14 (listed 2026-10-31). Each row
is one wallet's position in one market:

* ``user``, ``market``, ``size`` (+ long, - short), ``notional``, ``entry_price``;
* ``liquidation_price``, null when it cannot be computed;
* ``leverage_type`` (cross / isolated), ``leverage``, ``funding_pnl``, ``account_value``,
  ``account_mode``.

About 14 MiB a day for every market. Docs: https://docs.hydromancer.xyz/reservoir.
"""

from __future__ import annotations

from collections.abc import Sequence

import pyarrow as pa
import pyarrow.compute as pc

BUCKET = "hydromancer-reservoir"
REGION = "ap-northeast-1"
PERP_PREFIX = "global/snapshots/perp/all"


def day_prefix(date: str) -> str:
    """``20251215`` -> ``global/snapshots/perp/all/date=2025-12-15/``."""
    return f"{PERP_PREFIX}/date={date[:4]}-{date[4:6]}-{date[6:]}/"


def snapshot_state(key: str) -> tuple[int, int]:
    """``.../926030000_1773706027926.parquet`` -> (block 926030000, time 1773706027926 ms)."""
    block, _, ts_ms = key.rsplit("/", 1)[-1].removesuffix(".parquet").partition("_")
    return int(block), int(ts_ms)


def coin_snapshots(table: pa.Table, coins: Sequence[str], *, block: int, ts_ms: int) -> dict[str, pa.Table]:
    """The rows of each coin's market, stamped with the snapshot's block and time."""
    out = {}
    for coin in coins:
        rows = table.filter(pc.equal(table["market"], coin))
        out[coin] = rows.append_column("snapshot_block", pa.array([block] * rows.num_rows, pa.int64())).append_column(
            "snapshot_ts_ms", pa.array([ts_ms] * rows.num_rows, pa.int64())
        )
    return out
