"""Binance USD-M reference prices.

History: daily ``aggTrades`` from data.binance.vision (``bookTicker`` history
stopped on 2024-03-30, so it cannot cover 2025-26). Each zip has a ``.CHECKSUM``
(sha256) that is verified before use. Forward data: ``bookTicker`` lines from
the recorder (``local_ns raw_json``).

Licence: Binance Vision datasets are CC BY-NC-SA 4.0; see docs/jurisdiction.md.

CLI:

    python -m marketimmune.cli.download_binance aggtrades BTCUSDT 2025-12-01 2025-12-31
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterable
from datetime import date
from pathlib import Path

import polars as pl

BASE = "https://data.binance.vision/data/futures/um/daily/aggTrades"
AGG_COLUMNS = [
    "agg_trade_id",
    "price",
    "quantity",
    "first_trade_id",
    "last_trade_id",
    "transact_time",
    "is_buyer_maker",
]
AGG_SCHEMA = {
    "agg_trade_id": pl.Int64,
    "price": pl.Float64,
    "quantity": pl.Float64,
    "first_trade_id": pl.Int64,
    "last_trade_id": pl.Int64,
    "transact_time": pl.Int64,
    "is_buyer_maker": pl.Boolean,
}


def aggtrades_url(symbol: str, d: date) -> str:
    return f"{BASE}/{symbol}/{symbol}-aggTrades-{d.isoformat()}.zip"


def _get(url: str, timeout: float = 120.0, retries: int = 5) -> bytes:
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                data: bytes = r.read()
                return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            err: Exception = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            err = e
        time.sleep(2**attempt)
    raise RuntimeError(f"GET {url} failed after {retries} tries: {err}")


def parse_checksum(text: str) -> str:
    """``<sha256>  <filename>`` -> sha256."""
    return text.split(maxsplit=1)[0].strip().lower()


def download_aggtrades(symbol: str, d: date, dest: Path) -> Path:
    """Download and sha256-verify one day's zip; skip if a verified copy exists."""
    out = dest / symbol / f"{symbol}-aggTrades-{d.isoformat()}.zip"
    ok = out.with_suffix(".zip.sha256ok")
    if out.exists() and ok.exists():
        return out
    url = aggtrades_url(symbol, d)
    want = parse_checksum(_get(url + ".CHECKSUM").decode())
    blob = _get(url)
    got = hashlib.sha256(blob).hexdigest()
    if got != want:
        raise RuntimeError(f"{url}: sha256 {got} != {want}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)
    ok.write_text(want + "\n")
    return out


def read_aggtrades_zip(path: Path) -> pl.DataFrame:
    """Parse one daily zip. Older files have no header row; newer ones do."""
    with zipfile.ZipFile(path) as z:
        (name,) = z.namelist()
        raw = z.read(name)
    has_header = raw[:16].lower().startswith(b"agg_trade_id")
    df = pl.read_csv(
        io.BytesIO(raw), has_header=has_header, new_columns=AGG_COLUMNS, schema_overrides=AGG_SCHEMA
    )
    t = pl.from_epoch("transact_time", time_unit="ms").dt.cast_time_unit("ns").dt.replace_time_zone("UTC")
    return df.with_columns(t=t)


def trade_prices(df: pl.DataFrame) -> pl.DataFrame:
    """Reference price series from aggTrades: last trade price per millisecond."""
    return (
        df.group_by("transact_time", maintain_order=True)
        .agg(pl.col("price").last(), pl.col("t").last())
        .sort("transact_time")
        .select("t", pl.col("price").alias("px"))
    )


def book_ticker_lines(lines: Iterable[str]) -> pl.DataFrame:
    """Parse recorder lines ``<local_ns> <combined-stream JSON>`` for bookTicker."""
    rec = []
    for line in lines:
        ns, _, raw = line.partition(" ")
        if not raw:
            continue
        msg = json.loads(raw)
        d = msg.get("data", msg)
        if d.get("e") != "bookTicker":
            continue
        rec.append(
            {
                "local_ns": int(ns),
                "symbol": d["s"],
                "update_id": d["u"],
                "bid": float(d["b"]),
                "bid_qty": float(d["B"]),
                "ask": float(d["a"]),
                "ask_qty": float(d["A"]),
                "event_ms": d.get("E"),
                "transact_ms": d.get("T"),
            }
        )
    df = pl.DataFrame(
        rec,
        schema={
            "local_ns": pl.Int64,
            "symbol": pl.String,
            "update_id": pl.Int64,
            "bid": pl.Float64,
            "bid_qty": pl.Float64,
            "ask": pl.Float64,
            "ask_qty": pl.Float64,
            "event_ms": pl.Int64,
            "transact_ms": pl.Int64,
        },
    )
    return df.with_columns(mid=(pl.col("bid") + pl.col("ask")) / 2)


def main(argv: list[str] | None = None) -> int:
    from marketimmune.config import days

    ap = argparse.ArgumentParser(prog="python -m marketimmune.cli.download_binance")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("aggtrades", help="download and verify daily aggTrades zips")
    a.add_argument("symbol")
    a.add_argument("start")
    a.add_argument("end")
    a.add_argument("--dest", type=Path, default=Path("data/bronze/binance/aggTrades"))
    args = ap.parse_args(argv)
    for d in days(args.start, args.end):
        try:
            p = download_aggtrades(args.symbol, d, args.dest)
            print(f"{d} ok {p.stat().st_size / 1e6:.1f} MB")
        except urllib.error.HTTPError as e:
            print(f"{d} missing ({e.code})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
