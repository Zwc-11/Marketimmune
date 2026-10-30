from __future__ import annotations

from datetime import date
from typing import Any

from marketimmune.sources import hyperliquid_s3 as s3


class FakePaginator:
    def __init__(self, keys: dict[str, int]) -> None:
        self.keys = keys

    def paginate(self, Bucket: str, Prefix: str, Delimiter: str | None = None, **_: Any):
        under = sorted(k for k in self.keys if k.startswith(Prefix))
        if Delimiter:
            prefixes = sorted(
                {Prefix + k[len(Prefix) :].split("/", 1)[0] + "/" for k in under if "/" in k[len(Prefix) :]}
            )
            yield {"CommonPrefixes": [{"Prefix": p} for p in prefixes]}
        else:
            yield {"Contents": [{"Key": k, "Size": self.keys[k]} for k in under]}


class FakeS3:
    def __init__(self, keys: dict[str, int]) -> None:
        self.keys = keys

    def get_paginator(self, _name: str) -> FakePaginator:
        return FakePaginator(self.keys)


def test_start_height() -> None:
    assert s3.start_height("replica_cmds/20261021/1191310000.lz4") == 1191310000
    assert s3.start_height("replica_cmds/2025-07-01T00:00:00Z/20251215/840000000") == 840000000


def test_replica_day_flat_layout() -> None:
    fake = FakeS3(
        {
            "replica_cmds/20251215/20000.lz4": 5,
            "replica_cmds/20251215/10000.lz4": 7,
            "replica_cmds/20251216/30000.lz4": 1,
        }
    )
    objs = s3.replica_day(fake, date(2025, 12, 15))  # type: ignore[arg-type]
    assert [o.key for o in objs] == ["replica_cmds/20251215/10000.lz4", "replica_cmds/20251215/20000.lz4"]


def test_replica_day_node_layout_spans_restarts() -> None:
    fake = FakeS3(
        {
            "replica_cmds/A/20251215/10000": 1,
            "replica_cmds/A/20251214/0": 1,
            "replica_cmds/B/20251215/20000": 1,
            "replica_cmds/B/20251216/30000": 1,
        }
    )
    objs = s3.replica_day(fake, date(2025, 12, 15))  # type: ignore[arg-type]
    assert [o.key for o in objs] == ["replica_cmds/A/20251215/10000", "replica_cmds/B/20251215/20000"]


def test_fills_day_either_layout() -> None:
    a = FakeS3({"node_fills_by_block/hourly/20251215/10": 1, "node_fills_by_block/hourly/20251215/2": 1})
    assert [o.key.rsplit("/", 1)[1] for o in s3.fills_day(a, date(2025, 12, 15))] == ["2", "10"]  # type: ignore[arg-type]
    b = FakeS3({"node_fills_by_block/20251215/0.lz4": 1})
    assert len(s3.fills_day(b, date(2025, 12, 15))) == 1  # type: ignore[arg-type]


def test_cost_estimate() -> None:
    c = s3.cost_estimate(2000, 100 * 10**9, same_region=True)
    assert c["transfer_usd"] == 0 and c["requests_usd"] > 0
    assert s3.cost_estimate(1, 10**9, same_region=False)["transfer_usd"] > 0.1
