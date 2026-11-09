"""Recording boundaries must preserve the strategy's financial exposure."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marketimmune.cli import paper_report, paper_trade
from marketimmune.paper.engine import Engine, MarketMaker
from marketimmune.paper.events import RefTop, Top, Trade, parse_hl
from marketimmune.paper.live import RawWriter
from marketimmune.paper.provenance import prepare_run

STRATEGY = "hush@d=8/quiet=0/dd=50"


def engine() -> Engine:
    return Engine(("io:X",), strategies=(STRATEGY,), quote_usd=100, sz_decimals={"io:X": 2})


def populated() -> Engine:
    result = engine()
    result.handle(RefTop("io:X", 1000, 100, 100), 1000)
    result.handle(Top("io:X", 1000, 99, 10, 101, 10), 1000)
    result.handle(Trade("io:X", 1500, 98, 1, False, "wallet", 7), 1500)
    result.tick(1500)
    return result


def test_segment_keeps_inventory_entry_and_drawdown_without_double_counting_pnl(tmp_path: Path) -> None:
    first = populated()
    maker = first.makers["io:X"][0]
    before = maker.account.equity(100)
    first.save_state(tmp_path)
    second = engine()
    second.load_state(tmp_path)
    carried = second.makers["io:X"][0]
    assert isinstance(carried, MarketMaker) and isinstance(maker, MarketMaker)
    assert carried.qty == maker.qty and carried.account.position == 1
    assert carried.entry == maker.entry and carried.opened_ms == maker.opened_ms
    assert carried.account.equity(100) == 0
    assert before + carried.account.equity(90) == pytest.approx(maker.account.equity(90))
    assert second.portfolios[STRATEGY].peak == first.portfolios[STRATEGY].peak - before
    assert second.room(STRATEGY, "io:X") == first.room(STRATEGY, "io:X")
    assert ("io:X", 7) in second.trade_ids
    assert all(order.t_cancel <= 1700 for order in carried.orders)
    assert second.states["io:X"].book_received_ms is None
    with pytest.raises(ValueError, match="configuration differs"):
        Engine(("io:X",), strategies=("touch",)).load_state(tmp_path)


def test_verified_recording_can_start_with_inventory_and_a_pending_exit(tmp_path: Path) -> None:
    first = populated()
    maker = first.makers["io:X"][0]
    assert isinstance(maker, MarketMaker)
    maker.exit(1600, "hold", None)
    state = tmp_path / "state"
    first.save_state(state)
    live = engine()
    live.load_state(state)
    run = tmp_path / "run"
    prepare_run(live, run, state, paper_trade.SOURCE_SHA256)
    (run / "meta.json").write_text('{"io:X":2}', encoding="utf-8")
    writer = RawWriter(run / "raw")
    frame = {"channel": "bbo", "data": {"coin": "io:X", "time": 2000, "bbo": [{"px": "90", "sz": "0.25"}, {"px": "91", "sz": "1"}]}}
    writer.write("hl", 2000_000_000, json.dumps(frame))
    for event in parse_hl(frame, 2000):
        live.handle(event, 2000)
    writer.write("tick", 2100_000_000, b"2100 0")
    live.tick(2100)
    writer.close()
    assert live.makers["io:X"][0].account.position == 0.75
    live.write(run, final=True)
    assert paper_trade.main(["--out", str(tmp_path / "replay"), "--replay", str(run / "raw"), "--verify-recording"]) == 0


def test_report_handles_a_run_without_fills(tmp_path: Path) -> None:
    live = engine()
    live.handle(Top("io:X", 1000, 99, 10, 101, 10), 1000)
    live.tick(1000)
    live.write(tmp_path, final=True)
    report = paper_report.score([tmp_path])
    assert report["by_strategy"][0]["fills"] == 0
    assert report["by_strategy"][0]["total_usd"] == 0
    assert report["by_strategy"][0]["bps"] is None


def test_report_handles_an_empty_market_capture(tmp_path: Path) -> None:
    engine().write(tmp_path, final=True)
    assert paper_report.score([tmp_path])["by_strategy"] == []
