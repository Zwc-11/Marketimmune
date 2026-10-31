from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path

import pytest

from marketimmune.sources import binance_aggtrades as binance


def test_checksum_and_url() -> None:
    assert binance.parse_checksum("ABCdef  BTCUSDT-aggTrades-2025-12-15.zip\n") == "abcdef"
    assert binance.aggtrades_url("BTCUSDT", date(2025, 12, 15)).endswith(
        "/futures/um/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2025-12-15.zip"
    )


def test_verified_zip_is_not_downloaded_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "SOLUSDT" / "SOLUSDT-aggTrades-2025-12-15.zip"
    out.parent.mkdir()
    out.write_bytes(b"zip")
    out.with_suffix(".zip.sha256ok").write_text("x\n")
    monkeypatch.setattr(binance, "_get", lambda url: pytest.fail(f"fetched {url}"))
    assert binance.download_aggtrades("SOLUSDT", date(2025, 12, 15), tmp_path) == out


def test_download_checks_the_sha256(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(binance, "_get", lambda url: b"0" * 64 + b"  x.zip\n" if url.endswith(".CHECKSUM") else b"zip")
    with pytest.raises(AssertionError, match="sha256"):
        binance.download_aggtrades("SOLUSDT", date(2025, 12, 15), tmp_path)


@pytest.mark.network
def test_download_one_day_verified(tmp_path: Path) -> None:
    p = binance.download_aggtrades("SOLUSDT", date(2025, 12, 15), tmp_path)
    with zipfile.ZipFile(p) as z:
        (name,) = z.namelist()
    assert name == "SOLUSDT-aggTrades-2025-12-15.csv"
