from __future__ import annotations

import json
from pathlib import Path

import pytest

from marketimmune.cli import paper_trade
from marketimmune.paper.engine import Engine
from marketimmune.paper.events import RefTop, Top, Trade
from marketimmune.paper.live import RawWriter, raw_lines


def _engine() -> Engine:
    return Engine(("SOL",), latency_ms=100, quote_usd=1_000.0, max_quotes=5, maker_fee_bps=1.5, taker_fee_bps=4.5)


def test_maker_fills_after_latency_and_queue() -> None:
    e = _engine()
    e.handle(Top("SOL", 1_000, 99.0, 30.0, 101.0, 30.0), 1_000)  # qty = 10 coins; every maker quotes 99 / 101
    touch = next(m for m in e.makers["SOL"] if m.name == "touch")
    bid = touch.current[1]
    assert bid is not None and bid.px == 99.0 and bid.t_live == 1_100
    e.handle(Trade("SOL", 1_050, 99.0, 50.0, False, "0xa"), 1_060)  # before the order is in the book
    assert touch.account.fills == 0
    e.handle(Top("SOL", 1_150, 99.0, 25.0, 101.0, 30.0), 1_160)  # queue ahead: 25
    e.handle(Trade("SOL", 1_200, 99.0, 30.0, False, "0xa"), 1_210)  # 25 ahead, 5 for us
    assert touch.account.position == pytest.approx(5.0)
    assert touch.account.fees == pytest.approx(5 * 99 * 1.5e-4)
    e.handle(Trade("SOL", 1_250, 98.0, 1.0, False, "0xa"), 1_260)  # through the bid: the other 5
    assert touch.account.position == pytest.approx(10.0) and touch.account.fills == 2


def test_requote_cancels_after_latency() -> None:
    e = _engine()
    e.handle(Top("SOL", 1_000, 99.0, 30.0, 101.0, 30.0), 1_000)
    touch = next(m for m in e.makers["SOL"] if m.name == "touch")
    old = touch.current[1]
    e.handle(Top("SOL", 1_100, 100.0, 30.0, 101.0, 30.0), 1_100)  # the bid moves up: rejoin at 100
    assert old is not None and old.t_cancel == 1_200
    assert touch.current[1] is not None and touch.current[1].px == 100.0
    e.handle(Trade("SOL", 1_150, 98.0, 1.0, False, "0xa"), 1_160)  # the old order is still in the book
    assert touch.account.position == pytest.approx(10.0)


def test_taker_enters_on_the_gap_and_exits_after_the_hold() -> None:
    e = _engine()
    e.handle(Top("SOL", 1_000, 99.99, 30.0, 100.01, 30.0), 1_000)
    e.handle(RefTop("SOL", 1_000, 100.0, 100.0), 1_000)
    e.tick(1_000)  # basis = 0
    e.handle(RefTop("SOL", 1_030, 100.12, 100.12), 1_030)  # +12 bps
    taker = next(t for t in e.takers["SOL"] if t.name == "taker@10")
    assert taker.pending == (1, 1_130)
    e.handle(Top("SOL", 1_140, 100.04, 30.0, 100.06, 30.0), 1_400)
    assert taker.account.position == pytest.approx(10.0) and taker.entered_ms == 1_400
    e.handle(Top("SOL", 11_420, 100.09, 30.0, 100.11, 30.0), 11_420)  # 10 s on: send the exit
    assert taker.pending == (-1, 11_520)
    e.handle(Top("SOL", 11_600, 100.09, 30.0, 100.11, 30.0), 11_700)
    assert taker.account.position == 0.0
    assert taker.account.equity(100.0) == pytest.approx(10 * (100.09 - 100.06) - 10 * (100.06 + 100.09) * 4.5e-4)


def test_cli_replays_a_recording(tmp_path: Path) -> None:
    raw = tmp_path / "rec" / "raw"
    w = RawWriter(raw)
    (raw.parent / "meta.json").write_text('{"SOL": 2}')  # tick 0.01 at 100: no network call
    t0 = 1_793_900_000_000
    bbo = {
        "channel": "bbo",
        "data": {"coin": "SOL", "time": t0, "bbo": [{"px": "99", "sz": "30", "n": 1}, {"px": "101", "sz": "30", "n": 1}]},
    }
    trade = {"channel": "trades", "data": [{"coin": "SOL", "side": "A", "px": "98", "sz": "1", "time": t0 + 500, "users": ["0xb", "0xs"]}]}
    snap = {
        "channel": "l2_data",
        "sequence_num": 0,
        "events": [
            {
                "type": "snapshot",
                "product_id": "SOL-USD",
                "updates": [
                    {"side": "bid", "price_level": "99.9", "new_quantity": "1"},
                    {"side": "offer", "price_level": "100.1", "new_quantity": "1"},
                ],
            }
        ],
    }
    w.write("hl", t0 * 1_000_000, json.dumps(bbo))
    w.write("cb", (t0 + 10) * 1_000_000, json.dumps(snap))
    w.write("hl", (t0 + 600) * 1_000_000, json.dumps(trade))
    w.close()
    assert [v for _, v, _ in raw_lines(raw)] == ["hl", "cb", "hl"]
    out = tmp_path / "replayed"
    assert paper_trade.main(["--coins", "SOL", "--out", str(out), "--replay", str(raw), "--latency-ms", "100"]) == 0
    summary = json.loads((out / "summary.json").read_text())
    touch = next(r for r in summary["instances"] if r["strategy"] == "touch")
    assert touch["fills"] == 1 and touch["position_usd"] == pytest.approx(1_000.0)
    improve = next(r for r in summary["instances"] if r["strategy"] == "improve")
    assert improve["fills"] == 1  # bought at 99.01, a tick inside the 2.00 spread
    assert (out / "fills.jsonl").read_text().count("\n") == 7  # the seven makers, one fill each


def test_report_splits_the_pnl(tmp_path: Path) -> None:
    from marketimmune.cli import paper_report

    test_cli_replays_a_recording(tmp_path)
    out = tmp_path / "report.json"
    assert paper_report.main(["--runs", str(tmp_path / "replayed"), "--out", str(out)]) == 0
    row = next(r for r in json.loads(out.read_text())["by_coin"] if r["strategy"] == "touch")
    assert row["fills"] == 1 and row["total_usd"] == pytest.approx(10 - 990 * 1.5e-4, abs=0.01)
    notional = 990.0
    assert row["bps"]["spread"] == pytest.approx(10 / notional * 1e4, abs=0.01)  # bought at 99 against the 100 mid before the block
    assert row["bps"]["fee"] == pytest.approx(-1.5) and row["bps"]["inventory"] == pytest.approx(0.0, abs=0.01)
    assert row["break_even_fee_bps"] == pytest.approx(10 / notional * 1e4, abs=0.01)


def test_retimed_replay_moves_each_venue_and_keeps_time_order() -> None:
    from marketimmune.paper.live import retimed

    bbo = {"channel": "bbo", "data": {"coin": "SOL", "time": 1_000, "bbo": []}}
    old = {"channel": "trades", "data": [{"coin": "SOL", "side": "A", "px": "1", "sz": "1", "time": -9_000, "users": ["a", "b"]}]}
    lines = [
        (1_400 * 1_000_000, "hl", json.dumps(bbo).encode()),  # arrived 400 ms after its block
        (1_100 * 1_000_000, "cb", b"{}"),
        (1_500 * 1_000_000, "hl", json.dumps(old).encode()),  # the subscription replay: dropped
        (1_600 * 1_000_000, "hl", b'{"channel": "pong"}'),  # no block time: dropped
    ]
    out = [(t // 1_000_000, v) for t, v, _ in retimed(iter(sorted(lines)), {"hl": 50, "cb": 70})]
    assert out == [(1_050, "hl"), (1_170, "cb")]


def test_state_carries_wallets_and_model_rows(tmp_path: Path) -> None:
    e = _engine()
    e.wallets.add("0xa", 3.0)
    coin = e.states["SOL"]
    coin.rows, coin.row_ms, coin.row_mid, coin.basis = [[1.0] * 10, [2.0] * 10], [100, 200], [10.0, 10.1], 0.5
    e.save_state(tmp_path)
    f = _engine()
    f.load_state(tmp_path)
    assert f.wallets.count == {"0xa": 1} and f.states["SOL"].rows == coin.rows and f.states["SOL"].basis == 0.5
    assert f.states["SOL"].fitted_ms < 0  # refits at its first sample once the rows suffice


def test_raw_lines_survive_a_cut_file(tmp_path: Path) -> None:
    w = RawWriter(tmp_path)
    for k in range(200):
        w.write("hl", (1_793_900_000_000 + k) * 1_000_000, '{"channel": "pong"}' * 20)
    path = next(iter(w.files.values()))[1].name
    w.close()
    data = Path(path).read_bytes()
    Path(path).write_bytes(data[: len(data) - 30])  # cut before the gzip trailer
    lines = list(raw_lines(tmp_path))
    assert 0 < len(lines) <= 200 and all(msg.endswith(b"}") for _, _, msg in lines)
