from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from marketimmune.cli import backfill_day as cli
from tests.lake.test_backfill import payloads


def test_main_runs_with_injected_fetchers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = payloads()
    buckets: list[str] = []

    def fake_fetcher(bucket: str, region: str) -> Callable[[str], bytes]:
        buckets.append(bucket)
        return data.__getitem__

    monkeypatch.setattr(cli.s3, "fetcher", fake_fetcher)
    argv = ["--coin", "BTC", "--date", "20260101", "--hour", "0", "--fill-hour", "0", "--lake-root", str(tmp_path)]
    assert cli.main(argv) == 0
    out = json.loads(capsys.readouterr().out)
    assert buckets == ["hyperliquid-archive", "hl-mainnet-node-data"]
    assert (out["book_snapshots"], out["asset_contexts"], out["fills"], out["gold_rows"], out["training_rows"], len(out["writes"])) == (
        2,
        1,
        2,
        1,
        1,
        6,
    )
