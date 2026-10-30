"""Download the Albers et al. December 2025 L4 dataset from Zenodo.

Record: https://zenodo.org/records/18184441 (CC BY 4.0).

Standard library only, so it runs before the project environment exists:

    python marketimmune/sources/albers_download.py --dest data/bronze/albers --set needed
    python marketimmune/sources/albers_download.py --dest data/bronze/albers --set trades   # 6.7 GB

Zenodo throttles each connection to roughly 1 MB/s, so every large file is
split into byte-range segments fetched in parallel (8 segments x 2 files =
16 connections by default; measured ~33 MB/s with 8). Each segment resumes
from its own size, so the script can be stopped and rerun at any time. When a
file's segments are complete they are joined in one pass that also computes
the md5, which is checked against Zenodo's before the file is renamed into
place. A verified file gets a ``<name>.md5ok`` marker and is skipped on rerun.
``MANIFEST.json`` records what is on disk and verified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

RECORD_ID = "18184441"
API = f"https://zenodo.org/api/records/{RECORD_ID}"

DOCS = ["README.md", "SCHEMA.md", "read_data.py", "mapdir.tar.xz"]
SOL = ["sol_orders_202512.tar.xz", "sol_rejected_202512.tar.xz"]
ETH = ["eth_orders_202512.tar.xz", "eth_rejected_202512.tar.xz"]
BTC = ["btc_orders_202512.tar.xz", "btc_rejected_202512.tar.xz"]
DIFFS = ["book_diffs_202512.tar"]
# Trades for all coins with both counterparties, exact px/sz and each side's
# position before the trade (start_pos). MarketImmune v3 uses December for
# maker/taker labels and the forced-flow position roll-forward.
TRADES = ["trades_2025_12.tar"]

# Docs first, then everything one coin's replay needs (SOL is the smallest),
# then the larger coins. ``trades`` is a separate set so it can run after
# ``needed``; the Oct, Nov and Jan trades archives are not used.
SETS: dict[str, list[str]] = {
    "docs": DOCS,
    "sol": DOCS + DIFFS + SOL,
    "needed": DOCS + DIFFS + SOL + ETH + BTC,
    "trades": DOCS + TRADES,
}

CHUNK = 4 << 20  # 4 MiB reads
MIN_SEGMENT = 64 << 20  # files under 64 MiB use one connection
_print_lock = threading.Lock()
_progress: dict[str, int] = {}  # key -> bytes on disk, for the monitor thread


@dataclass
class RemoteFile:
    key: str
    size: int
    md5: str
    url: str


def log(msg: str) -> None:
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with _print_lock:
        print(f"{stamp} {msg}", flush=True)


def fetch_index() -> dict[str, RemoteFile]:
    with urllib.request.urlopen(API, timeout=60) as r:
        meta = json.load(r)
    out = {}
    for f in meta["files"]:
        algo, digest = f["checksum"].split(":", 1)
        if algo != "md5":
            raise ValueError(f"unexpected checksum type {algo} for {f['key']}")
        out[f["key"]] = RemoteFile(f["key"], int(f["size"]), digest, f["links"]["self"])
    return out


def split(size: int, segments: int) -> list[tuple[int, int]]:
    """Half-open byte ranges [start, end) covering [0, size)."""
    n = max(1, min(segments, size // MIN_SEGMENT or 1))
    step = -(-size // n)
    return [(s, min(s + step, size)) for s in range(0, size, step)]


def fetch_range(url: str, start: int, end: int, path: Path, key: str, max_retries: int = 100) -> None:
    """Fill ``path`` with bytes [start, end) of ``url``, resuming from its size."""
    attempt = 0
    while True:
        have = path.stat().st_size if path.exists() else 0
        want = end - start
        if have > want:
            log(f"{key}: {path.name} longer than its range; restarting it")
            path.unlink()
            have = 0
        if have == want:
            return
        req = urllib.request.Request(url, headers={"Range": f"bytes={start + have}-{end - 1}"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                if r.status != 206:
                    raise RuntimeError(f"{key}: server ignored Range (HTTP {r.status})")
                with path.open("ab") as fh:
                    while block := r.read(CHUNK):
                        fh.write(block)
                        with _print_lock:
                            _progress[key] = _progress.get(key, 0) + len(block)
            attempt = 0
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            attempt += 1
            if attempt > max_retries:
                raise RuntimeError(f"{key}: {path.name} failed after {max_retries} retries") from e
            wait = min(300, 2 ** min(attempt, 8))
            log(f"{key}: {path.name} {type(e).__name__}: {e}; retry {attempt} in {wait}s")
            time.sleep(wait)


def download(rf: RemoteFile, dest: Path, segments: int) -> Path:
    final = dest / rf.key
    marker = dest / f"{rf.key}.md5ok"
    if final.exists() and marker.exists() and final.stat().st_size == rf.size:
        log(f"skip {rf.key} (verified)")
        return final

    segdir = dest / f"{rf.key}.parts"
    segdir.mkdir(exist_ok=True)
    plan_path = segdir / "plan.json"
    if plan_path.exists():  # keep the original split on resume
        ranges = [tuple(r) for r in json.loads(plan_path.read_text())["ranges"]]
    else:
        ranges = split(rf.size, segments)
        plan_path.write_text(json.dumps({"size": rf.size, "md5": rf.md5, "ranges": ranges}))
        legacy = dest / f"{rf.key}.part"  # single-stream partial from an older run
        if legacy.exists() and legacy.stat().st_size <= ranges[0][1] - ranges[0][0]:
            legacy.rename(segdir / "seg000")
    seg_paths = [segdir / f"seg{i:03d}" for i in range(len(ranges))]
    with _print_lock:
        _progress[rf.key] = sum(p.stat().st_size for p in seg_paths if p.exists())

    log(f"{rf.key}: {rf.size / 1e9:.2f} GB in {len(ranges)} segment(s)")
    with ThreadPoolExecutor(max_workers=len(ranges)) as pool:
        futs = [
            pool.submit(fetch_range, rf.url, s, e, p, rf.key)
            for (s, e), p in zip(ranges, seg_paths, strict=True)
        ]
        for f in as_completed(futs):
            f.result()

    log(f"{rf.key}: joining segments and checking md5")
    tmp = dest / f"{rf.key}.joining"
    h = hashlib.md5()
    with tmp.open("wb") as out:
        for p in seg_paths:
            with p.open("rb") as fh:
                while block := fh.read(CHUNK):
                    h.update(block)
                    out.write(block)
    if h.hexdigest() != rf.md5:
        tmp.replace(dest / f"{rf.key}.bad")  # replace: rename fails on Windows if it exists
        raise RuntimeError(f"{rf.key}: md5 {h.hexdigest()} != {rf.md5}; kept as {rf.key}.bad")
    tmp.replace(final)
    marker.write_text(rf.md5 + "\n")
    try:
        shutil.rmtree(segdir)
    except OSError as e:  # e.g. a sandbox that forbids deletes; harmless leftovers
        log(f"{rf.key}: could not remove {segdir.name} ({e}); delete it by hand")
    log(f"{rf.key}: verified")
    return final


def monitor(total: int, stop: threading.Event, every_s: float = 60.0) -> None:
    t0 = time.time()
    with _print_lock:
        start = sum(_progress.values())
    while not stop.wait(every_s):
        with _print_lock:
            done = sum(_progress.values())
        rate = (done - start) / max(time.time() - t0, 1e-9) / 1e6
        eta_h = (total - done) / 1e6 / rate / 3600 if rate > 0 else float("inf")
        log(
            f"progress {done / 1e9:.1f}/{total / 1e9:.1f} GB ({100 * done / total:.1f}%) "
            f"{rate:.1f} MB/s, eta {eta_h:.1f} h"
        )


def write_manifest(dest: Path, index: dict[str, RemoteFile], keys: list[str]) -> None:
    """Record ``keys`` plus every file an earlier run already listed, so running
    another set (``--set trades`` after ``needed``) never drops rows."""
    path = dest / "MANIFEST.json"
    listed: list[str] = []
    if path.exists():
        try:
            listed = [r["key"] for r in json.loads(path.read_text())["files"]]
        except (ValueError, KeyError, TypeError):
            listed = []
    ordered = list(dict.fromkeys([k for k in listed if k in index] + keys))
    rows = [
        {**asdict(index[k]), "verified": (dest / f"{k}.md5ok").exists() and (dest / k).exists()}
        for k in ordered
    ]
    manifest = {
        "record": f"https://zenodo.org/records/{RECORD_ID}",
        "doi": "10.5281/zenodo.18184441",
        "license": "CC-BY-4.0",
        "files": rows,
    }
    path.write_text(json.dumps(manifest, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Download the Albers Dec 2025 L4 dataset.")
    ap.add_argument("--dest", type=Path, default=Path("data/bronze/albers"))
    ap.add_argument("--set", choices=sorted(SETS), default="needed")
    ap.add_argument("--jobs", type=int, default=2, help="files in parallel")
    ap.add_argument("--segments", type=int, default=8, help="connections per file")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    args.dest.mkdir(parents=True, exist_ok=True)
    index = fetch_index()
    keys = SETS[args.set]
    missing = [k for k in keys if k not in index]
    if missing:
        log(f"not in record: {missing}")
        return 2
    total = sum(index[k].size for k in keys)
    log(
        f"set={args.set}: {len(keys)} files, {total / 1e9:.1f} GB -> {args.dest} "
        f"({args.jobs} files x {args.segments} connections)"
    )
    if args.dry_run:
        for k in keys:
            log(f"  {k} {index[k].size / 1e9:.2f} GB md5={index[k].md5}")
        return 0

    for k in keys:  # count verified files as done so the progress line is honest
        if (args.dest / f"{k}.md5ok").exists():
            _progress[k] = index[k].size
    stop = threading.Event()
    threading.Thread(target=monitor, args=(total, stop), daemon=True).start()

    failures = 0
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futs = {pool.submit(download, index[k], args.dest, args.segments): k for k in keys}
        for fut in as_completed(futs):
            try:
                fut.result()
            except Exception as e:  # report every file, then fail at the end
                failures += 1
                log(f"FAILED {futs[fut]}: {e}")
            write_manifest(args.dest, index, keys)
    stop.set()
    log("done" if not failures else f"done with {failures} failure(s); rerun to resume")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
