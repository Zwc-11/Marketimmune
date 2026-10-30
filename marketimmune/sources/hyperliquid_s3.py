"""Requester-pays access to Hyperliquid's S3 buckets.

``hl-mainnet-node-data`` (ap-northeast-1) holds ``replica_cmds`` (every signed
action, by block) and ``node_fills_by_block``. The requester pays for requests
and transfer, so: list and stream from an instance in Tokyo, where transfer to
EC2 in the same region is free, and download only compact Parquet.

Layouts seen so far (confirm with :func:`discover`; the official bucket may differ
from third-party copies):

- ``replica_cmds/<start_time>/<YYYYMMDD>/<start_height>`` (node's own layout)
  or ``replica_cmds/<YYYYMMDD>/<start_height>.lz4``. Each file holds 10,000
  blocks; line ``i`` is block ``start_height + i + 1``.
- ``node_fills_by_block/hourly/<YYYYMMDD>/<H>`` or ``node_fills_by_block/<YYYYMMDD>/<H>.lz4``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

NODE_BUCKET = "hl-mainnet-node-data"
ARCHIVE_BUCKET = "hyperliquid-archive"
NODE_REGION = "ap-northeast-1"
ARCHIVE_REGION = "us-east-1"
RP: dict[str, Any] = {"RequestPayer": "requester"}

# Published AWS prices (check before budgeting; they change): S3 Standard GET
# $0.00037 per 1,000 in ap-northeast-1; transfer S3 -> EC2 in the same region
# free; transfer out to the internet ~$0.114/GB for the first 10 TB in Tokyo.
GET_PER_1000_USD = 0.00037
EGRESS_INTERNET_USD_PER_GB = 0.114

_DATE = re.compile(r"^\d{8}$")


def client(region: str = NODE_REGION) -> S3Client:
    import boto3

    return boto3.client("s3", region_name=region)


@dataclass(frozen=True)
class Obj:
    key: str
    size: int


def list_objects(s3: S3Client, prefix: str, bucket: str = NODE_BUCKET) -> Iterator[Obj]:
    pages = s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix, **RP)
    for page in pages:
        for o in page.get("Contents", []):
            yield Obj(o["Key"], int(o["Size"]))


def list_prefixes(s3: S3Client, prefix: str, bucket: str = NODE_BUCKET) -> list[str]:
    """Immediate sub-"directories" of ``prefix`` (which should end in ``/``)."""
    pages = s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix, Delimiter="/", **RP)
    out: list[str] = []
    for page in pages:
        out.extend(p["Prefix"] for p in page.get("CommonPrefixes", []))
    return out


def yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")


def start_height(key: str) -> int:
    """Start height encoded in a ``replica_cmds`` file name (``.../1191310000[.lz4]``)."""
    name = key.rsplit("/", 1)[-1]
    return int(name.removesuffix(".lz4"))


def replica_day_prefixes(s3: S3Client, d: date) -> list[str]:
    """Every prefix holding ``replica_cmds`` files for day ``d``, either layout."""
    day = yyyymmdd(d)
    top = list_prefixes(s3, "replica_cmds/")
    if any(p.rstrip("/").rsplit("/", 1)[-1] == day for p in top):
        return [f"replica_cmds/{day}/"]
    out = []
    for start_time in top:  # node layout: replica_cmds/<start_time>/<date>/
        if f"{start_time}{day}/" in list_prefixes(s3, start_time):
            out.append(f"{start_time}{day}/")
    return out


def replica_day(s3: S3Client, d: date) -> list[Obj]:
    """All ``replica_cmds`` files for a day, sorted by start height."""
    objs = [o for p in replica_day_prefixes(s3, d) for o in list_objects(s3, p)]
    return sorted(objs, key=lambda o: start_height(o.key))


def fills_day(s3: S3Client, d: date) -> list[Obj]:
    """``node_fills_by_block`` hourly files for a day, sorted by hour."""
    day = yyyymmdd(d)
    for prefix in (f"node_fills_by_block/hourly/{day}/", f"node_fills_by_block/{day}/"):
        objs = list(list_objects(s3, prefix))
        if objs:
            return sorted(objs, key=lambda o: int(o.key.rsplit("/", 1)[-1].removesuffix(".lz4")))
    return []


def download(s3: S3Client, key: str, dest: Path, bucket: str = NODE_BUCKET) -> Path:
    """Download one object (requester pays) unless an equal-size copy exists."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    head = s3.head_object(Bucket=bucket, Key=key, **RP)
    if dest.exists() and dest.stat().st_size == head["ContentLength"]:
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    s3.download_file(bucket, key, str(tmp), ExtraArgs=RP)
    tmp.replace(dest)
    return dest


def cost_estimate(n_objects: int, total_bytes: int, *, same_region: bool) -> dict[str, float]:
    """Rough requester-pays cost of fetching ``n_objects`` totalling ``total_bytes``."""
    requests = n_objects / 1000 * GET_PER_1000_USD
    transfer = 0.0 if same_region else total_bytes / 1e9 * EGRESS_INTERNET_USD_PER_GB
    return {"requests_usd": requests, "transfer_usd": transfer, "total_usd": requests + transfer}
