from __future__ import annotations

import json
from pathlib import Path

import pytest

from marketimmune.cli import fee_tiers


def _row(day: str, maker: str, notional: float, pnl: float, fee_bps: float = 1.5) -> dict[str, object]:
    return {"day": day, "maker": maker, "fills": 10, "notional_usd": notional, "fee_usd": -fee_bps / 1e4 * notional, "pnl_usd": pnl}


def test_pnl_at_each_tier_and_break_even(tmp_path: Path) -> None:
    days = tmp_path / "days"
    days.mkdir()
    # before the fee the maker makes 0.2 bp a day on $1M: break-even is a fee of +0.2 bp
    for d in ("20251201", "20251202", "20251203", "20251204"):
        (days / f"{d}.json").write_text(json.dumps([_row(d, "S1", 1e6, 20.0 - 150.0)]))
    report = tmp_path / "sim.json"
    daily = [_row("20251201", "stale/fifo", 5e5, -10.0), _row("20251201", "stale/risk_averse", 5e5, 99.0)]
    daily += [
        _row("20251201", "S1/fifo", 1e6, 1e9),
        _row("20251209", "stale/fifo", 5e5, 1e9),
    ]  # S1 already given; Dec 9 not in the first input
    report.write_text(json.dumps({"daily": daily}))
    out = tmp_path / "tiers.json"
    assert fee_tiers.main(["--coin", "sol", "--inputs", str(days), str(report), "--out", str(out)]) == 0
    result = json.loads(out.read_text())
    s1 = result["makers"]["S1"]
    assert s1["break_even_fee_bps"] == pytest.approx(0.2)
    assert s1["tiers"]["base"]["mean_daily_usd"] == pytest.approx(-130.0)
    assert s1["tiers"]["volume_500m"]["mean_daily_usd"] == pytest.approx(20.0)
    assert s1["tiers"]["rebate_3pct"]["mean_daily_usd"] == pytest.approx(50.0)
    assert s1["profitable_from"] == "volume_500m"  # 0.4 bp still costs more than the 0.2 bp edge
    stale = result["makers"]["stale"]
    assert stale["days"] == 1 and stale["break_even_fee_bps"] == pytest.approx((-10.0 + 75.0) / 5e5 * 1e4)
    assert set(result["makers"]) == {"S1", "stale"}
