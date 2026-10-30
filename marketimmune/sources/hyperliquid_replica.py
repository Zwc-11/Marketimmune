"""Python prototype reader for ``replica_cmds`` (Lesson 3.1).

The production path is the Rust extractor in ``hl-replay``; this module serves
the G0 probe and the tests, and it is deliberately tolerant: unknown action
types are counted, never rejected.

One line = one block::

    {"abci_block": {"time": "...", "round": ..., "proposer": ...,
                    "signed_action_bundles": [[bundle_hash, {"signed_actions": [
                        {"action": {...}, "nonce": ..., "signature": {...},
                         "vaultAddress": ..., "expiresAfter": ...}, ...]}], ...]},
     "resps": {"Full": [[bundle_hash, [{"res": {"status": "ok", "response": ...},
                                        "user": ...}, ...]], ...]}}

``resps``, when present, is aligned with the bundles and, inside each bundle,
with the signed actions. Whether the official files carry it is G0 question 1.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BATCH_SIZE = 10_000  # blocks per file (the SDK's REPLICA_CMD_BATCH_SIZE)


def parse_time_ms(s: str) -> int:
    """``2026-01-01T00:00:00.123456789`` (UTC, up to ns) -> epoch milliseconds."""
    whole, _, frac = s.partition(".")
    base = datetime.fromisoformat(whole).replace(tzinfo=UTC)
    ms = int(base.timestamp()) * 1000
    return ms + int((frac + "000")[:3]) if frac else ms


def parse_time_ns(s: str) -> int:
    whole, _, frac = s.partition(".")
    base = datetime.fromisoformat(whole).replace(tzinfo=UTC)
    return int(base.timestamp()) * 1_000_000_000 + int((frac + "000000000")[:9])


def blocks(path: Path, start_height: int) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yield ``(height, record)``; height = start + line index + 1."""
    import lz4.frame

    with lz4.frame.open(path, "rt") as fh:
        for i, line in enumerate(fh):
            if line.strip():
                yield start_height + i + 1, json.loads(line)


def bundles(rec: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    blk = rec.get("abci_block", rec)
    out = []
    for item in blk.get("signed_action_bundles", []):
        bundle_hash, body = item[0], item[1]
        out.append((bundle_hash, body.get("signed_actions", [])))
    return out


def responses(rec: dict[str, Any]) -> list[list[dict[str, Any]]] | None:
    """Per-bundle lists of per-action results, or ``None`` if the file has none."""
    resps = rec.get("resps")
    if resps is None:
        return None
    full = resps.get("Full", resps) if isinstance(resps, dict) else resps
    out: list[list[dict[str, Any]]] = []
    for item in full:
        results = item[1] if isinstance(item, list) and len(item) == 2 else item
        out.append(list(results))
    return out


def order_statuses(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Statuses of an ``order`` action's orders from its response, if any.

    Response shape (API): ``{"type": "order", "data": {"statuses": [{"resting":
    {"oid": 1}}, {"filled": {"oid": 2, ...}}, {"error": "..."}]}}``.
    """
    res = result.get("res", result)
    resp = res.get("response")
    if not isinstance(resp, dict):
        return []
    data = resp.get("data", resp)
    st = data.get("statuses") if isinstance(data, dict) else None
    return list(st) if isinstance(st, list) else []


def status_oid(status: dict[str, Any] | str) -> int | None:
    if isinstance(status, dict):
        for k in ("resting", "filled"):
            if isinstance(status.get(k), dict) and "oid" in status[k]:
                return int(status[k]["oid"])
    return None


def priority_of(action: dict[str, Any]) -> int:
    """``grouping.p`` of an order action (0 when absent or a plain grouping string)."""
    g = action.get("grouping")
    return int(g.get("p", 0)) if isinstance(g, dict) else 0


def actions(
    height: int, rec: dict[str, Any], keep_assets: set[int] | None = None
) -> Iterator[dict[str, Any]]:
    """Flatten one block into order / cancel rows (the Lesson 3.1 prototype).

    Orders carry their response status and oid when ``resps`` is present.
    ``modify`` / ``batchModify`` rows carry the order they place, tagged with the
    oid they replace; other action types are skipped (count them separately).
    """
    blk = rec.get("abci_block", rec)
    t_ms = parse_time_ms(blk["time"])
    resps = responses(rec)
    for b, (_hash, sas) in enumerate(bundles(rec)):
        for k, sa in enumerate(sas):
            a = sa["action"]
            base = {
                "height": height,
                "t_block_ms": t_ms,
                "bundle": b,
                "pos": k,
                "nonce": sa.get("nonce"),
                "vault": sa.get("vaultAddress"),
                "sig": sa.get("signature"),
            }
            result = resps[b][k] if resps is not None and b < len(resps) and k < len(resps[b]) else None
            if result is not None:
                base["resp_user"] = result.get("user")
            typ = a.get("type")
            if typ == "order":
                statuses = order_statuses(result) if result else []
                prio = priority_of(a)
                for j, o in enumerate(a.get("orders", [])):
                    if keep_assets is not None and o["a"] not in keep_assets:
                        continue
                    st = statuses[j] if j < len(statuses) else None
                    yield {
                        **base,
                        **_order_fields(o),
                        "kind": "order",
                        "prio": prio,
                        "status": _status_kind(st),
                        "oid": status_oid(st) if st else None,
                    }
            elif typ == "cancel":
                for c in a.get("cancels", []):
                    if keep_assets is None or c["a"] in keep_assets:
                        yield {**base, "kind": "cancel", "asset": c["a"], "oid": c["o"], "fast": a.get("f")}
            elif typ == "cancelByCloid":
                for c in a.get("cancels", []):
                    asset = c.get("asset", c.get("a"))
                    if keep_assets is None or asset in keep_assets:
                        yield {**base, "kind": "cancel_cloid", "asset": asset, "cloid": c.get("cloid")}
            elif typ in ("modify", "batchModify"):
                mods = [a] if typ == "modify" else a.get("modifies", [])
                for m in mods:
                    o = m["order"]
                    if keep_assets is None or o["a"] in keep_assets:
                        yield {
                            **base,
                            **_order_fields(o),
                            "kind": "modify",
                            "replaces": m.get("oid"),
                            "prio": 0,
                            "status": None,
                            "oid": None,
                        }


def _order_fields(o: dict[str, Any]) -> dict[str, Any]:
    t = o.get("t", {})
    tif = t.get("limit", {}).get("tif") if isinstance(t, dict) else None
    return {
        "asset": o["a"],
        "is_buy": o["b"],
        "px": o["p"],
        "sz": o["s"],
        "reduce_only": o.get("r"),
        "tif": tif,
        "trigger": "trigger" in t if isinstance(t, dict) else False,
        "cloid": o.get("c"),
    }


def _status_kind(st: dict[str, Any] | str | None) -> str | None:
    if st is None:
        return None
    if isinstance(st, str):
        return st
    return next(iter(st.keys()), None)
