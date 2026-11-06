from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from marketimmune.paper.funding import fetch_funding, funding_for_run, funding_payments


def test_held_positions_settle_hourly_funding() -> None:
    # Audit G02: a perp position held over the hour pays (long, rate > 0) or receives funding.
    hour = 3_600_000
    eq = pd.DataFrame(
        {
            "t_ms": [hour - 60_000, hour + 60_000, 2 * hour - 60_000, 2 * hour + 60_000, hour - 60_000, 2 * hour + 60_000],
            "coin": ["BTC"] * 4 + ["ETH"] * 2,
            "strategy": ["gap@0.1"] * 4 + ["gap@0.1"] * 2,
            "position_usd": [1_000.0, -500.0, -500.0, 0.0, 2_000.0, 2_000.0],
        }
    )
    rates = {"BTC": [(0, 1.0), (hour, 1e-4), (2 * hour, 2e-4), (3 * hour, 9.0)], "ETH": [(hour, -1e-4)]}
    out = funding_payments(eq, rates).set_index("coin")
    # BTC: long $1,000 pays 0.10 at the first hour; short $500 receives 0.10 at the second; the
    # rates before the first and after the last snapshot are outside the run.
    assert out.loc["BTC", "funding_usd"] == pytest.approx(-0.1 + 0.1)
    assert out.loc["BTC", "settlements"] == 2
    assert out.loc["ETH", "funding_usd"] == pytest.approx(0.2)  # long $2,000 receives at a negative rate


def test_funding_rates_are_paged_and_cached(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def post(body: dict[str, Any]) -> list[dict[str, Any]]:
        calls.append(body)
        start = body["startTime"]
        return [{"time": start + i, "fundingRate": "0.0001"} for i in range(500 if start == 0 else 3)]

    rates = fetch_funding(["BTC"], 0, 10_000, post)
    assert len(rates["BTC"]) == 503 and [c["startTime"] for c in calls] == [0, 500]
    (tmp_path / "equity.jsonl").write_text(json.dumps({"t_ms": 0, "coin": "BTC", "strategy": "s", "position_usd": 0.0}) + "\n")
    assert funding_for_run(tmp_path, post)["BTC"] == [(0, 0.0001)]  # only the run's own span
    assert funding_for_run(tmp_path, lambda body: pytest.fail("cached"))["BTC"][0] == (0, 0.0001)


def test_a_maker_rebate_is_income() -> None:
    # Audit B22's point for the paper ledger: a negative maker fee (a rebate) adds to PnL.
    from marketimmune.paper.orders import Account

    account = Account()
    account.fill(0, 1, 100.0, 1.0, -0.0001)  # bought 1 at 100 with a 1 bp rebate
    assert account.equity(100.0) == pytest.approx(0.01)
