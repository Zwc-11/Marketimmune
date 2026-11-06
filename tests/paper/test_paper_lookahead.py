from __future__ import annotations

import json
from pathlib import Path

from marketimmune.cli import paper_lookahead
from marketimmune.paper.live import RawWriter


def _recording(raw: Path) -> None:
    """Twenty seconds of SOL: a moving Hyperliquid top, trades from two wallets, a Coinbase book."""
    w = RawWriter(raw)
    (raw.parent / "meta.json").write_text('{"SOL": 2}')
    t0 = 1_793_900_000_000
    snap = {
        "channel": "l2_data",
        "sequence_num": 0,
        "events": [
            {
                "type": "snapshot",
                "product_id": "SOL-USD",
                "updates": [
                    {"side": "bid", "price_level": "99.99", "new_quantity": "5"},
                    {"side": "offer", "price_level": "100.01", "new_quantity": "5"},
                ],
            }
        ],
    }
    w.write("cb", (t0 + 5) * 1_000_000, json.dumps(snap))
    for k in range(40):
        t = t0 + 500 * k
        bid = 99.98 + 0.01 * (k % 5)
        bbo = {
            "channel": "bbo",
            "data": {
                "coin": "SOL",
                "time": t,
                "bbo": [{"px": f"{bid:.2f}", "sz": "30", "n": 1}, {"px": f"{bid + 0.04:.2f}", "sz": "30", "n": 1}],
            },
        }
        w.write("hl", (t + 300) * 1_000_000, json.dumps(bbo))
        cb_px = 99.99 + 0.01 * ((k + 2) % 5)
        upd = {
            "channel": "l2_data",
            "sequence_num": k + 1,
            "events": [
                {
                    "type": "update",
                    "product_id": "SOL-USD",
                    "updates": [{"side": "bid", "price_level": f"{cb_px:.2f}", "new_quantity": "5"}],
                }
            ],
        }
        w.write("cb", (t + 20) * 1_000_000, json.dumps(upd))
        if k % 3 == 0:
            side = "A" if k % 2 else "B"
            px = f"{bid:.2f}" if side == "A" else f"{bid + 0.04:.2f}"
            trade = {
                "channel": "trades",
                "data": [{"coin": "SOL", "side": side, "px": px, "sz": "40", "time": t + 100, "users": [f"0x{k % 2}", "0xm"]}],
            }
            w.write("hl", (t + 400) * 1_000_000, json.dumps(trade))
    w.close()


def test_decisions_before_a_cut_do_not_change_when_later_data_is_removed(tmp_path: Path) -> None:
    raw = tmp_path / "rec" / "raw"
    _recording(raw)
    out = tmp_path / "lookahead.json"
    argv = ["--replay", str(raw), "--coins", "SOL", "--strategies", "touch,zgap@0.05,guard@z=0.05/w=1,mm@1", "--cuts", "0.5,0.8"]
    argv += ["--quote-usd", "1000", "--latency-ms", "100", "--out", str(out)]
    assert paper_lookahead.main(argv) == 0
    report = json.loads(out.read_text())
    assert report["identical"]
    cut = report["cuts"][1]
    assert cut["streams"]["decisions"]["rows"] > 0 and cut["signals"]["rows"] > 0
