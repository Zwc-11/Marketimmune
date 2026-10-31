"""Pull Hydromancer's daily position snapshots for some coins (``marketimmune.sources.hydromancer``).

    python -m marketimmune.cli.pull_snapshots --dates 20251215..20251231 --coins BTC,ETH,SOL --out data/bronze/hydromancer

Writes ``<out>/<COIN>/<COIN>-<YYYYMMDD>.parquet`` with the snapshot's block and time as columns.
A date with no capture (2025-10-25 to 12-14) is reported and skipped. At 14 MiB a day, pulling
straight to a home machine costs about $0.002 a day of transfer.
"""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from marketimmune.sources.hydromancer import BUCKET, REGION, coin_snapshots, day_prefix, snapshot_state
from marketimmune.sources.hyperliquid_s3 import RP, client, list_objects
from marketimmune.utils import parse_date_spec, parse_symbol_spec


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dates", required=True, help="YYYYMMDD, lists or a..b ranges")
    parser.add_argument("--coins", default="BTC,ETH,SOL")
    parser.add_argument("--out", type=Path, default=Path("data/bronze/hydromancer"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    coins = parse_symbol_spec(args.coins)
    s3 = client(REGION)
    for date in parse_date_spec(args.dates):
        objs = [o for o in list_objects(s3, day_prefix(date), bucket=BUCKET) if o.key.endswith(".parquet")]
        if not objs:
            print(json.dumps({"date": date, "missing": True}), flush=True)
            continue
        parts: dict[str, list[pa.Table]] = {c: [] for c in coins}
        for o in objs:
            block, ts_ms = snapshot_state(o.key)
            table = pq.read_table(io.BytesIO(s3.get_object(Bucket=BUCKET, Key=o.key, **RP)["Body"].read()))
            for coin, rows in coin_snapshots(table, coins, block=block, ts_ms=ts_ms).items():
                parts[coin].append(rows)
        for coin, tables in parts.items():
            path = args.out / coin / f"{coin}-{date}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.concat_tables(tables), path, compression="zstd")
        print(
            json.dumps({"date": date, "states": len(objs), "positions": {c: sum(t.num_rows for t in parts[c]) for c in coins}}), flush=True
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
