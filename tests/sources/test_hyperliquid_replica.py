from __future__ import annotations

from pathlib import Path

import lz4.frame
import pytest

from marketimmune.sources import hyperliquid_replica as replica
from tests.conftest import block_line, load_path

SIG = {"r": "0x1", "s": "0x2", "v": 27}


def order_action(asset: int, is_buy: bool, px: str, tif: str, prio: int | None) -> dict:
    grouping: object = {"p": prio} if prio is not None else "na"
    return {
        "type": "order",
        "grouping": grouping,
        "orders": [{"a": asset, "b": is_buy, "p": px, "s": "0.1", "r": False, "t": {"limit": {"tif": tif}}}],
    }


def write_file(tmp: Path, start: int, with_resps: bool) -> Path:
    lines = []
    for i in range(3):
        h = start + i + 1
        t = f"2025-12-15T12:00:0{i}.{i}50000000"
        sas = [
            {
                "action": order_action(0, True, "100.0", "Alo", None),
                "nonce": 1765800000000 + i * 1000 - 80,
                "signature": SIG,
            },
            {
                "action": order_action(0, False, "99.0", "Ioc", 40000),
                "nonce": 1765800000000 + i * 1000 - 30,
                "signature": SIG,
                "vaultAddress": None,
            },
            {
                "action": {"type": "cancel", "cancels": [{"a": 0, "o": 555}], "f": True},
                "nonce": 1765800000000 + i * 1000 - 20,
                "signature": SIG,
            },
            {
                "action": {
                    "type": "modify",
                    "oid": 777,
                    "order": {
                        "a": 5,
                        "b": True,
                        "p": "150",
                        "s": "1",
                        "r": False,
                        "t": {"limit": {"tif": "Gtc"}},
                    },
                },
                "nonce": 1765800000000 + i * 1000 - 10,
                "signature": SIG,
            },
            {"action": {"type": "usdSend", "amount": "1"}, "nonce": 1765800000000, "signature": SIG},
        ]
        resps = (
            [
                [
                    {
                        "res": {
                            "status": "ok",
                            "response": {
                                "type": "order",
                                "data": {"statuses": [{"resting": {"oid": 900 + i}}]},
                            },
                        },
                        "user": "0xmaker",
                    },
                    {
                        "res": {
                            "status": "ok",
                            "response": {
                                "type": "order",
                                "data": {
                                    "statuses": [
                                        {"filled": {"oid": 950 + i, "totalSz": "0.1", "avgPx": "99.0"}}
                                    ]
                                },
                            },
                        },
                        "user": "0xsniper",
                    },
                    {
                        "res": {
                            "status": "ok",
                            "response": {"type": "cancel", "data": {"statuses": ["success"]}},
                        },
                        "user": "0xmaker",
                    },
                    {"res": {"status": "ok", "response": {"type": "default"}}, "user": "0xm2"},
                    {"res": {"status": "err", "response": "Insufficient balance"}, "user": None},
                ]
            ]
            if with_resps
            else None
        )
        lines.append(block_line(h, t, [sas], resps))
    path = tmp / f"{start}"
    with lz4.frame.open(path, "wt") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def test_parse_time() -> None:
    assert replica.parse_time_ms("2025-12-15T12:00:00.123456789") == 1765800000123
    assert replica.parse_time_ns("2025-12-15T12:00:00.123456789") == 1765800000123456789
    assert replica.parse_time_ms("2025-12-15T12:00:00") == 1765800000000


def test_blocks_heights_and_actions(tmp_path: Path) -> None:
    p = write_file(tmp_path, 1_000_000, with_resps=True)
    blocks = list(replica.blocks(p, 1_000_000))
    assert [h for h, _ in blocks] == [1_000_001, 1_000_002, 1_000_003]
    rows = [r for h, rec in blocks for r in replica.actions(h, rec)]
    kinds = [r["kind"] for r in rows]
    assert kinds.count("order") == 6 and kinds.count("cancel") == 3 and kinds.count("modify") == 3
    first = rows[0]
    assert (first["tif"], first["status"], first["oid"], first["prio"]) == ("Alo", "resting", 900, 0)
    snipe = rows[1]
    assert (snipe["tif"], snipe["status"], snipe["oid"], snipe["prio"]) == ("Ioc", "filled", 950, 40000)
    assert snipe["resp_user"] == "0xsniper"
    cancel = rows[2]
    assert (cancel["oid"], cancel["fast"]) == (555, True)
    assert rows[3]["replaces"] == 777 and rows[3]["asset"] == 5
    only_sol = [r for h, rec in blocks for r in replica.actions(h, rec, keep_assets={5})]
    assert {r["kind"] for r in only_sol} == {"modify"}


def test_probe_counts_and_verdicts(tmp_path: Path) -> None:
    probe = load_path("probe", "marketimmune/cli/probe_s3_day.py")
    with_r = probe.probe_file(write_file(tmp_path, 2_000_000, with_resps=True), 2_000_000)
    assert with_r["blocks"] == 3 and with_r["heights_contiguous"] and with_r["height_field_mismatches"] == 0
    assert with_r["actions"] == 15 and with_r["orders"] == 6 and with_r["orders_with_priority"] == 3
    assert with_r["resps"]["blocks_aligned"] == 3 and with_r["resps"]["orders_with_oid"] == 6
    assert with_r["counts"]["cancel_f"] == {"True": 3}
    assert with_r["counts"]["action_types"]["usdSend"] == 3
    # Block i is at i s + 50 + 100 i ms; the four trading actions sit 60-230 ms
    # behind it, the usdSend nonce is fixed, so only its block-0 delay is in range.
    assert with_r["nonce_delay_ms"]["share_0_1000"] == pytest.approx(13 / 15)
    v = probe.verdicts([with_r])
    assert v["q1_resps_present"] and v["q1_share_orders_with_oid"] == 1.0
    assert v["q3_e1_dates"].startswith("any replica_cmds date")

    without = probe.probe_file(write_file(tmp_path, 3_000_000, with_resps=False), 3_000_000)
    v2 = probe.verdicts([without])
    assert not v2["q1_resps_present"] and v2["q3_e1_dates"].startswith("Dec 2025")
