from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from marketimmune.cli import priority_fee_bands, pull_candles
from marketimmune.priority.fees import BANDS, band_stats, fee_band, fill_markouts, hype_usd, trade_mids
from marketimmune.priority.fills import to_frame

T0 = datetime(2026, 5, 1, tzinfo=UTC)


def _leg(block: int, ms: int, tid: int, crossed: bool, side: str, px: float, sz: float = 1.0, gas: float | None = None) -> dict[str, Any]:
    t = (T0 + timedelta(milliseconds=ms)).strftime("%Y-%m-%dT%H:%M:%S.%f000")
    return {
        "block_number": block, "block_time": t, "local_time": t, "user": "0x1", "coin": "SOL", "px": px, "sz": sz, "side": side,
        "time_ms": int(T0.timestamp() * 1000) + ms, "start_position": 0.0, "dir": "", "closed_pnl": 0.0, "hash": "0x0",
        "oid": tid * 10 + crossed, "crossed": crossed, "fee": 0.0, "fee_token": "USDC", "tid": tid, "cloid": None, "twap_id": None,
        "liquidation": False, "liquidated_user": None, "liquidation_mark_px": None, "liquidation_method": None, "builder_fee": None,
        "priority_gas": gas,
    }  # fmt: skip


def _trade(block: int, ms: int, tid: int, taker_buys: bool, px: float, gas: float | None = None) -> list[dict[str, Any]]:
    side = "B" if taker_buys else "A"
    return [_leg(block, ms, tid, True, side, px, gas=gas), _leg(block, ms, tid, False, "A" if taker_buys else "B", px)]


def _legs() -> pl.DataFrame:
    """Taker sells at 99.9, buys at 100.1 (mid 100), then a taker paying 4 bps buys at 100.1 and
    the market lifts: buys at 100.5, sells at 100.3 (mid 100.4)."""
    rows = [
        *_trade(1, 0, 1, False, 99.9),
        *_trade(2, 100, 2, True, 100.1),
        *_trade(3, 200, 3, True, 100.1, gas=100.1 * 4e-4 / 20.0),  # 4 bps of $100.1 at HYPE $20
        *_trade(4, 600, 4, True, 100.5),
        *_trade(4, 600, 5, False, 100.3),
    ]
    return to_frame(rows)


def _hype(tmp_path: Path) -> Path:
    d = tmp_path / "candles"
    d.mkdir()
    t = int(T0.timestamp() * 1000)
    pl.DataFrame({"t": [t - 3_600_000, t], "o": [19.0, 20.0], "h": [21.0, 21.0], "l": [19.0, 19.0], "c": [21.0, 20.0]}).write_parquet(
        d / "HYPE-1h.parquet"
    )
    pl.DataFrame({"t": [t - 14_400_000, t], "o": [1.0, 5.0], "h": [1.0, 5.0], "l": [1.0, 5.0], "c": [1.0, 5.0]}).write_parquet(
        d / "HYPE-4h.parquet"
    )
    return d


def test_bands_and_hype_price(tmp_path: Path) -> None:
    fees = pl.DataFrame({"f": [0.0, 0.5, 2.0, 3.0, 8.0, 9.0]})
    assert fees.select(fee_band(pl.col("f")).alias("band"))["band"].to_list() == ["0", "0-2", "0-2", "2-4", "4-8", "8+"]
    hype = hype_usd(_hype(tmp_path))
    assert hype["hype_usd"].to_list() == [1.0, 20.0, 20.0]  # 4-hour candles only before the first hourly one


def test_trade_mids_carry_each_side_forward() -> None:
    mids = trade_mids(_legs())
    assert mids["mid"].to_list() == pytest.approx([99.9, 100.0, 100.0, 100.4])  # one side known: the last price


def test_fee_bps_and_markouts(tmp_path: Path) -> None:
    trades = fill_markouts(_legs(), hype_usd(_hype(tmp_path)), horizons_s=(0.5,))
    paid = trades.filter(pl.col("tid") == 3).row(0, named=True)
    assert paid["fee_bps"] == pytest.approx(4.0) and paid["band"] == "2-4"
    # the maker sold at 100.1 with the mid at 100 before and 100.4 half a second later
    assert paid["hs_bps"] == pytest.approx(10.0) and paid["mo_0.5s"] == pytest.approx(-30.0)
    stats = band_stats(trades, horizons_s=(0.5,))
    assert set(stats["band"]) <= set(BANDS) and stats["fills"].sum() == trades.drop_nulls("mo_0.5s").height


def test_cli_days_then_report(tmp_path: Path) -> None:
    node = tmp_path / "node" / "SOL"
    node.mkdir(parents=True)
    _legs().write_parquet(node / "SOL-20260501.parquet")
    common = ["--coins", "SOL", "--dates", "20260501", "--node-dir", str(tmp_path / "node"), "--candles-dir", str(_hype(tmp_path))]
    common += ["--out", str(tmp_path / "bands")]
    assert priority_fee_bands.main(common) == 0
    assert priority_fee_bands.main([*common, "--report", str(tmp_path / "r.json")]) == 0
    r = json.loads((tmp_path / "r.json").read_text())["coins"]["SOL"]
    assert r["rollout_first_fee_date"] == "20260501"
    assert r["since_rollout"]["2-4"]["fills"] == 1 and r["fee_bps_quantiles"]["q50"] == pytest.approx(4.01)
    assert r["units_check"][0]["fills_3.9_4.1"] == 1


def test_pull_candles_merges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int, int]] = []

    def fake(coin: str, interval: str, start: int, end: int) -> list[dict[str, Any]]:
        calls.append((interval, start, end))
        return [{"t": start, "o": "1", "h": "2", "l": "0.5", "c": "1.5"}]

    monkeypatch.setattr(pull_candles, "fetch_candles", fake)
    argv = ["--dates", "20260501..20260502", "--out", str(tmp_path), "--intervals", "1h"]
    assert pull_candles.main(argv) == 0 and pull_candles.main(argv) == 0
    frame = pl.read_parquet(tmp_path / "HYPE-1h.parquet")
    assert frame.height == 1 and frame["c"].item() == 1.5
    assert calls[0][2] - calls[0][1] == 2 * 86_400_000


def test_trade_mids_take_the_last_executed_prices() -> None:
    # one block listed out of execution order (and with trade ids in no useful order): buy order
    # 50 fills at 100.1, then buy order 70 sweeps 100.2 and 100.4; sell order 60 sweeps 99.9 then
    # 99.7. The block's last buy is 100.4 and its last sell 99.7.
    fills = [(9, 70, True, 100.4), (1, 60, False, 99.7), (5, 50, True, 100.1), (3, 70, True, 100.2), (7, 60, False, 99.9)]
    rows = []
    for tid, oid, buys, px in fills:
        taker, maker = _trade(1, 0, tid, buys, px)
        rows += [{**taker, "oid": oid}, {**maker, "oid": 1000 + tid}]
    assert trade_mids(to_frame(rows))["mid"].to_list() == [pytest.approx((100.4 + 99.7) / 2)]
