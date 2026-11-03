from __future__ import annotations

import pyarrow as pa

from marketimmune.sources.hydromancer import coin_snapshots, day_prefix, snapshot_state


def test_snapshot_paths_and_coin_filter() -> None:
    assert day_prefix("20251215") == "global/snapshots/perp/all/date=2025-12-15/"
    assert snapshot_state("global/snapshots/perp/all/date=2026-03-17/926030000_1773706027926.parquet") == (926030000, 1773706027926)
    table = pa.table(
        {
            "user": ["0xa", "0xb", "0xc"],
            "market": ["SOL", "BTC", "xyz:MSFT"],
            "size": [10.0, -0.5, 3.0],
            "liquidation_price": [120.0, None, 1.0],
        }
    )
    out = coin_snapshots(table, ["SOL", "ETH"], block=7, ts_ms=1_765_000_000_000)
    assert out["SOL"].to_pylist() == [
        {"user": "0xa", "market": "SOL", "size": 10.0, "liquidation_price": 120.0, "snapshot_block": 7, "snapshot_ts_ms": 1_765_000_000_000}
    ]
    assert out["ETH"].num_rows == 0 and out["ETH"].schema.names[-2:] == ["snapshot_block", "snapshot_ts_ms"]
