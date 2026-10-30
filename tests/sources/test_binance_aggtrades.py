from __future__ import annotations

import io
import json
import zipfile
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from marketimmune.sources import binance_aggtrades as binance

ROWS = "1,100.5,0.2,10,11,1765800000000,true\n2,100.6,0.1,12,12,1765800000001,false\n"


def make_zip(path: Path, header: bool) -> Path:
    body = (
        "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker\n"
        if header
        else ""
    ) + ROWS
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("BTCUSDT-aggTrades-2025-12-15.csv", body)
    path.write_bytes(buf.getvalue())
    return path


@pytest.mark.parametrize("header", [True, False])
def test_read_aggtrades(tmp_path: Path, header: bool) -> None:
    df = binance.read_aggtrades_zip(make_zip(tmp_path / "x.zip", header))
    assert df.height == 2 and df["price"].to_list() == [100.5, 100.6]
    assert df["is_buyer_maker"].to_list() == [True, False]
    assert df["t"].dtype == pl.Datetime("ns", "UTC")


def test_checksum_and_url() -> None:
    assert binance.parse_checksum("ABCdef  BTCUSDT-aggTrades-2025-12-15.zip\n") == "abcdef"
    assert binance.aggtrades_url("BTCUSDT", date(2025, 12, 15)).endswith(
        "/futures/um/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2025-12-15.zip"
    )


def test_book_ticker_lines() -> None:
    msg = {
        "stream": "btcusdt@bookTicker",
        "data": {
            "e": "bookTicker",
            "u": 1,
            "s": "BTCUSDT",
            "b": "100.0",
            "B": "1.5",
            "a": "100.2",
            "A": "2",
            "T": 5,
            "E": 6,
        },
    }
    df = binance.book_ticker_lines([f"123 {json.dumps(msg)}", '456 {"result":null,"id":1}', ""])
    assert df.height == 1 and df["mid"][0] == pytest.approx(100.1) and df["local_ns"][0] == 123


@pytest.mark.network
def test_download_one_day_verified(tmp_path: Path) -> None:
    p = binance.download_aggtrades("SOLUSDT", date(2025, 12, 15), tmp_path)
    df = binance.read_aggtrades_zip(p)
    assert df.height > 100_000
    assert df["t"].min().date() == date(2025, 12, 15)  # type: ignore[union-attr]
