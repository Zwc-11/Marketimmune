"""Download Binance USD-M daily ``aggTrades`` zips (the CEX reference price).

History comes from data.binance.vision (``bookTicker`` history stopped on 2024-03-30, so
it cannot cover 2025-26). Each zip has a ``.CHECKSUM`` (sha256) that is verified before
the zip is kept; :func:`marketimmune.features.cex_gap.read_binance_aggtrades_zip` reads
it. Licence: Binance Vision datasets are CC BY-NC-SA 4.0; see docs/jurisdiction.md.

    python -m marketimmune.cli.download_binance aggtrades SOLUSDT 2025-12-01 2025-12-31
"""

from __future__ import annotations

import argparse
import hashlib
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from marketimmune.config import days

BASE = "https://data.binance.vision/data/futures/um/daily/aggTrades"


def aggtrades_url(symbol: str, d: date) -> str:
    return f"{BASE}/{symbol}/{symbol}-aggTrades-{d.isoformat()}.zip"


def _get(url: str, timeout: float = 120.0, retries: int = 5) -> bytes:
    """GET with exponential backoff; a 404 (day not published) is raised at once."""
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
    assert got == want, f"{url}: sha256 {got} != {want}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)
    ok.write_text(want + "\n")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m marketimmune.cli.download_binance")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("aggtrades", help="download and verify daily aggTrades zips")
    a.add_argument("symbol")
    a.add_argument("start", help="YYYY-MM-DD")
    a.add_argument("end", help="YYYY-MM-DD, inclusive")
    a.add_argument("--dest", type=Path, default=Path("data/bronze/binance/aggTrades"))
    args = ap.parse_args(argv)
    for d in days(args.start, args.end):
        try:
            p = download_aggtrades(args.symbol, d, args.dest)
            print(f"{d} ok {p.stat().st_size / 1e6:.1f} MB")
        except urllib.error.HTTPError as e:  # days Binance has not published yet
            print(f"{d} missing ({e.code})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
