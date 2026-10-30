"""Gate G0 probe: one day of ``replica_cmds`` and ``node_fills_by_block``.

Run on the Tokyo spot instance (deploy/ec2_tokyo.md), where S3 -> EC2 transfer
is free. It answers, and writes to ``eval/probe_<date>.json``:

1. Are responses (``resps``) in ``replica_cmds``, and do they carry order ids?
2. What one processed day costs (bytes, files, measured throughput, $).
3. Which dates E1 can use (follows from 1).
4. Is ``priorityGas`` present on BTC fills that day (the launch scan runs
   ``python -m marketimmune.cli.find_first_priority_day first-priority`` over many days).

Also recorded: whether ``grouping.p`` and the cancel ``f`` flag appear, the
nonce-delay distribution, action-type counts, and height arithmetic.
Raw examples (with addresses and signatures) go to ``data/logs/``, which is
gitignored; the committed JSON holds counts and distributions only.

    python -m marketimmune.cli.probe_s3_day --date 2025-12-15 --files 3 --usd-per-hour 0.35
    python -m marketimmune.cli.probe_s3_day --local path/to/1191310000.lz4   # offline check
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from marketimmune.config import RESULTS, paths
from marketimmune.sources import hyperliquid_replica as replica

MAX_DELAYS = 5_000_000  # cap memory for the delay sample


def probe_file(path: Path, start: int, examples: dict[str, list[Any]] | None = None) -> dict[str, Any]:
    """Parse one replica_cmds file and count everything G0 asks about."""
    c: dict[str, Counter[str]] = {
        k: Counter()
        for k in (
            "top_keys",
            "block_keys",
            "action_types",
            "grouping",
            "tif",
            "order_status",
            "cancel_f",
            "sa_keys",
            "resp_status",
        )
    }
    n_blocks = n_actions = n_orders = n_prio = n_resp_user = n_resp_actions = 0
    resp_aligned = resp_misaligned = height_field_mismatch = 0
    prio_values: list[int] = []
    delays: list[int] = []
    heights: list[int] = []
    times: list[int] = []
    oid_linked = 0
    t0 = time.perf_counter()
    for h, rec in replica.blocks(path, start):
        n_blocks += 1
        heights.append(h)
        c["top_keys"].update(rec.keys())
        blk = rec.get("abci_block", {})
        c["block_keys"].update(blk.keys())
        if "height" in rec and int(rec["height"]) != h:
            height_field_mismatch += 1
        t_ms = replica.parse_time_ms(blk["time"])
        times.append(t_ms)
        bnds = replica.bundles(rec)
        resps = replica.responses(rec)
        if resps is not None:
            if len(resps) == len(bnds) and all(
                len(r) == len(s) for r, (_, s) in zip(resps, bnds, strict=True)
            ):
                resp_aligned += 1
            else:
                resp_misaligned += 1
        for b, (_hash, sas) in enumerate(bnds):
            for k, sa in enumerate(sas):
                n_actions += 1
                a = sa["action"]
                typ = a.get("type", "?")
                c["action_types"][typ] += 1
                c["sa_keys"].update(sa.keys())
                if isinstance(sa.get("nonce"), int) and len(delays) < MAX_DELAYS:
                    delays.append(t_ms - sa["nonce"])
                if examples is not None and len(examples.setdefault(typ, [])) < 3:
                    examples[typ].append(sa)
                result = resps[b][k] if resps and b < len(resps) and k < len(resps[b]) else None
                if result is not None:
                    n_resp_actions += 1
                    n_resp_user += result.get("user") is not None
                    c["resp_status"][str(result.get("res", {}).get("status"))] += 1
                if typ == "order":
                    g = a.get("grouping")
                    c["grouping"]["dict" if isinstance(g, dict) else str(g)] += 1
                    p = replica.priority_of(a)
                    if p > 0:
                        n_prio += 1
                        prio_values.append(p)
                    statuses = replica.order_statuses(result) if result else []
                    for j, o in enumerate(a.get("orders", [])):
                        n_orders += 1
                        t = o.get("t", {})
                        c["tif"][str(t.get("limit", {}).get("tif") if "limit" in t else "trigger")] += 1
                        st = statuses[j] if j < len(statuses) else None
                        kind = replica._status_kind(st) if st is not None else "none"
                        c["order_status"][str(kind)] += 1
                        if st is not None and replica.status_oid(st) is not None:
                            oid_linked += 1
                elif typ == "cancel":
                    c["cancel_f"][str(a.get("f", "absent"))] += 1
    secs = time.perf_counter() - t0
    hs = np.array(heights)
    ts = np.array(times)
    d = np.array(delays, dtype=np.int64) if delays else np.array([0])
    qs = [0.001, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 0.999]
    gaps = np.diff(ts) if ts.size > 1 else np.array([0])
    return {
        "file": path.name,
        "start_height": start,
        "blocks": n_blocks,
        "heights_contiguous": bool(hs.size == 0 or np.all(np.diff(hs) == 1)),
        "height_field_mismatches": height_field_mismatch,
        "block_time_ms": {
            "first": int(ts.min()) if ts.size else None,
            "last": int(ts.max()) if ts.size else None,
            "decreases": int((gaps < 0).sum()),
            "interval_mean_ms": float(gaps.mean()),
            "interval_p05_ms": float(np.quantile(gaps, 0.05)),
            "interval_p95_ms": float(np.quantile(gaps, 0.95)),
        },
        "actions": n_actions,
        "orders": n_orders,
        "orders_with_priority": n_prio,
        "priority_p": (
            {
                "min": int(min(prio_values)),
                "median": float(np.median(prio_values)),
                "max": int(max(prio_values)),
            }
            if prio_values
            else None
        ),
        "resps": {
            "blocks_aligned": resp_aligned,
            "blocks_misaligned": resp_misaligned,
            "actions_with_result": n_resp_actions,
            "results_with_user": n_resp_user,
            "orders_with_oid": oid_linked,
        },
        "nonce_delay_ms": {
            "n": int(d.size),
            "share_0_1000": float(((d >= 0) & (d <= 1000)).mean()),
            "share_negative": float((d < 0).mean()),
            **{f"q{q:g}": float(np.quantile(d, q)) for q in qs},
        },
        "counts": {k: dict(v.most_common(40)) for k, v in c.items()},
        "parse_seconds": secs,
        "bytes_compressed": path.stat().st_size,
    }


def verdicts(files: list[dict[str, Any]]) -> dict[str, Any]:
    acts = sum(f["actions"] for f in files)
    with_res = sum(f["resps"]["actions_with_result"] for f in files)
    orders = sum(f["orders"] for f in files)
    linked = sum(f["resps"]["orders_with_oid"] for f in files)
    cancels_f = Counter[str]()
    for f in files:
        cancels_f.update(f["counts"]["cancel_f"])
    resps_present = with_res > 0
    return {
        "q1_resps_present": resps_present,
        "q1_share_actions_with_result": with_res / acts if acts else 0.0,
        "q1_share_orders_with_oid": linked / orders if orders else 0.0,
        "q3_e1_dates": (
            "any replica_cmds date: order ids link to actions through resps"
            if resps_present and linked
            else "Dec 2025 (Albers), Dwellir order statuses from 2026-01-22, or own-node windows"
        ),
        "grouping_p_seen": any(f["orders_with_priority"] for f in files),
        "cancel_f_values": dict(cancels_f),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", type=date.fromisoformat)
    ap.add_argument("--local", type=Path, help="probe a replica_cmds file already on disk")
    ap.add_argument("--files", type=int, default=3, help="files to sample (first, middle, last ...)")
    ap.add_argument("--fill-hours", type=int, nargs="*", default=[0, 12, 23])
    ap.add_argument("--usd-per-hour", type=float, default=None, help="instance price, for the cost line")
    ap.add_argument("--scratch", type=Path, default=Path("/tmp/pop-probe"))
    args = ap.parse_args(argv)
    if not args.date and not args.local:
        ap.error("give --date (S3) or --local")

    logs = paths().logs
    logs.mkdir(parents=True, exist_ok=True)
    examples: dict[str, list[Any]] = {}
    out: dict[str, Any] = {"probe_version": 1, "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    if args.local:
        start = int(args.local.name.removesuffix(".lz4"))
        files = [probe_file(args.local, start, examples)]
        out.update({"mode": "local", "files": files, **verdicts(files)})
        tag = args.local.name
    else:
        from marketimmune.priority import fills as fills_mod
        from marketimmune.sources import hyperliquid_s3 as s3m

        s3 = s3m.client()
        objs = s3m.replica_day(s3, args.date)
        if not objs:
            print(f"no replica_cmds files found for {args.date}", file=sys.stderr)
            return 2
        total = sum(o.size for o in objs)
        starts = [s3m.start_height(o.key) for o in objs]
        steps = sorted({b - a for a, b in itertools.pairwise(starts)})
        idx = sorted({round(i * (len(objs) - 1) / max(args.files - 1, 1)) for i in range(args.files)})
        files, dl_secs = [], 0.0
        for i in idx:
            o = objs[i]
            local = args.scratch / o.key.replace("/", "_")
            t0 = time.perf_counter()
            s3m.download(s3, o.key, local)
            dl_secs += time.perf_counter() - t0
            r = probe_file(local, s3m.start_height(o.key), examples)
            r["key"] = o.key
            files.append(r)
        sampled = sum(f["bytes_compressed"] for f in files)
        secs = dl_secs + sum(f["parse_seconds"] for f in files)
        day_hours = total / (sampled / secs) / 3600 if secs else None
        cost = s3m.cost_estimate(len(objs), total, same_region=True)
        if args.usd_per_hour is not None and day_hours is not None:
            cost["instance_usd"] = day_hours * args.usd_per_hour
            cost["total_usd"] += cost["instance_usd"]
        out.update(
            {
                "mode": "s3",
                "date": args.date.isoformat(),
                "replica_cmds": {
                    "files": len(objs),
                    "bytes_compressed": total,
                    "gb_compressed": total / 1e9,
                    "first_key": objs[0].key,
                    "last_key": objs[-1].key,
                    "start_height_steps": steps[:5],
                },
                "files": files,
                "q2_one_day": {
                    "python_prototype_hours_single_core": day_hours,
                    "cost": cost,
                    "note": "single-threaded Python; the Rust extractor sets the real number",
                },
                **verdicts(files),
            }
        )
        # Fills: size for the day and priorityGas on BTC in sampled hours.
        fobjs = s3m.fills_day(s3, args.date)
        fsum: dict[str, Any] = {"files": len(fobjs), "bytes_compressed": sum(o.size for o in fobjs)}
        hours = [o for o in fobjs if int(o.key.rsplit("/", 1)[-1].removesuffix(".lz4")) in args.fill_hours]
        prio_btc = 0
        for o in hours:
            local = args.scratch / o.key.replace("/", "_")
            s3m.download(s3, o.key, local)
            df = fills_mod.read_lz4(local)
            prio_btc += df.filter((df["coin"] == "BTC") & (df["priority_gas"].fill_null(0) > 0)).height
        fsum["sampled_hours"] = [o.key for o in hours]
        fsum["btc_fills_with_priority_gas"] = prio_btc
        out["node_fills_by_block"] = fsum
        out["q4_btc_priority_gas_seen_this_day"] = prio_btc > 0
        tag = args.date.isoformat()

    RESULTS.mkdir(exist_ok=True)
    dest = RESULTS / f"probe_{tag}.json"
    dest.write_text(json.dumps(out, indent=2, default=str) + "\n")
    (logs / f"probe_{tag}_examples.json").write_text(json.dumps(examples, indent=1, default=str)[:5_000_000])
    print(json.dumps({k: v for k, v in out.items() if k.startswith("q")}, indent=2, default=str))
    print(f"wrote {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
