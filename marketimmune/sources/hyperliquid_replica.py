"""Python reader for ``replica_cmds``, the signed-action log; the G0 probe uses it.

The Rust extractor in ``crates/hl-replay`` is the production path. One line is one block::

    {"abci_block": {"time": "...", "round": ..., "proposer": ...,
                    "signed_action_bundles": [[bundle_hash, {"signed_actions": [
                        {"action": {...}, "nonce": ..., "signature": {...},
                         "vaultAddress": ..., "expiresAfter": ...}, ...]}], ...]},
     "resps": {"Full": [[bundle_hash, [{"res": {"status": "ok", "response": ...},
                                        "user": ...}, ...]], ...]}}

``resps``, when present, is aligned with the bundles and, inside each bundle, with the
signed actions; whether the official files carry it is G0 question 1.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import lz4.frame

BATCH_SIZE = 10_000  # blocks per file (the SDK's REPLICA_CMD_BATCH_SIZE)


def parse_time_ms(s: str) -> int:
    """``2026-01-01T00:00:00.123456789`` (UTC, up to ns) -> epoch milliseconds."""
    whole, _, frac = s.partition(".")
    ms = int(datetime.fromisoformat(whole).replace(tzinfo=UTC).timestamp()) * 1000
    return ms + int((frac + "000")[:3])


def blocks(path: Path, start_height: int) -> Iterator[tuple[int, dict[str, Any]]]:
    """``(height, record)`` per line; line ``i`` is block ``start_height + i + 1``."""
    with lz4.frame.open(path, "rt") as fh:
        for height, line in enumerate(fh, start=start_height + 1):
            yield height, json.loads(line)


def bundles(rec: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    return [(bundle_hash, body["signed_actions"]) for bundle_hash, body in rec["abci_block"]["signed_action_bundles"]]


def responses(rec: dict[str, Any]) -> list[list[dict[str, Any]]] | None:
    """Per-bundle lists of per-action results, or ``None`` when the block has no ``resps``."""
    return [results for _hash, results in rec["resps"]["Full"]] if "resps" in rec else None


def order_statuses(result: dict[str, Any]) -> list[Any]:
    """``{"resting": {"oid"}}``, ``{"filled": {"oid", ...}}`` or ``{"error": ...}`` per order; ``[]`` for an error response."""
    response = result["res"]["response"]
    return response["data"]["statuses"] if isinstance(response, dict) and "data" in response else []


def status_oid(status: dict[str, Any] | str) -> int | None:
    if isinstance(status, dict):
        for kind in ("resting", "filled"):
            if kind in status:
                oid: int = status[kind]["oid"]
                return oid
    return None


def status_kind(status: dict[str, Any] | str | None) -> str | None:
    return status if status is None or isinstance(status, str) else next(iter(status))


def priority_of(action: dict[str, Any]) -> int:
    """``grouping.p`` of an order action (0 for a plain grouping string such as ``"na"``)."""
    grouping = action["grouping"]
    p: int = grouping["p"] if isinstance(grouping, dict) else 0
    return p


def actions(height: int, rec: dict[str, Any], keep_assets: set[int] | None = None) -> Iterator[dict[str, Any]]:
    """Flatten one block into order, cancel and modify rows; other action types are skipped.

    Orders carry their response status and oid when ``resps`` is present. ``modify`` and
    ``batchModify`` rows carry the order they place, tagged with the oid they replace.
    """
    t_ms = parse_time_ms(rec["abci_block"]["time"])
    resps = responses(rec)
    for b, (_hash, signed) in enumerate(bundles(rec)):
        for k, sa in enumerate(signed):
            action = sa["action"]
            base: dict[str, Any] = {
                "height": height,
                "t_block_ms": t_ms,
                "bundle": b,
                "pos": k,
                "nonce": sa["nonce"],
                "vault": sa.get("vaultAddress"),
                "sig": sa["signature"],
            }
            result = resps[b][k] if resps is not None else None
            if result is not None:
                base["resp_user"] = result["user"]
            kind = action["type"]
            if kind == "order":
                statuses = order_statuses(result) if result is not None else []
                prio = priority_of(action)
                for j, order in enumerate(action["orders"]):
                    if keep_assets is None or order["a"] in keep_assets:
                        status = statuses[j] if j < len(statuses) else None
                        yield (
                            base
                            | _order_fields(order)
                            | {"kind": "order", "prio": prio, "status": status_kind(status), "oid": status_oid(status) if status else None}
                        )
            elif kind == "cancel":
                for c in action["cancels"]:
                    if keep_assets is None or c["a"] in keep_assets:
                        yield base | {"kind": "cancel", "asset": c["a"], "oid": c["o"], "fast": action.get("f")}
            elif kind == "cancelByCloid":
                for c in action["cancels"]:
                    if keep_assets is None or c["asset"] in keep_assets:
                        yield base | {"kind": "cancel_cloid", "asset": c["asset"], "cloid": c["cloid"]}
            elif kind in ("modify", "batchModify"):
                for m in [action] if kind == "modify" else action["modifies"]:
                    if keep_assets is None or m["order"]["a"] in keep_assets:
                        yield (
                            base
                            | _order_fields(m["order"])
                            | {"kind": "modify", "replaces": m["oid"], "prio": 0, "status": None, "oid": None}
                        )


def _order_fields(order: dict[str, Any]) -> dict[str, Any]:
    t = order["t"]
    return {
        "asset": order["a"],
        "is_buy": order["b"],
        "px": order["p"],
        "sz": order["s"],
        "reduce_only": order["r"],
        "tif": t["limit"]["tif"] if "limit" in t else None,
        "trigger": "trigger" in t,
        "cloid": order.get("c"),
    }
