"""Requester-pays access to Hyperliquid's S3 buckets (needs the ``aws`` extra).

``hl-mainnet-node-data`` (ap-northeast-1) holds ``replica_cmds`` (every signed action, by
block) and ``node_fills_by_block/hourly/<YYYYMMDD>/<H>.lz4``; ``hyperliquid-archive``
(us-east-1) holds L2 books and asset contexts. The requester pays for requests and
transfer, so list and stream from an instance in Tokyo, where transfer to EC2 in the same
region is free, and download only compact Parquet.

``replica_cmds`` has two layouts in the wild, both handled until the G0 probe settles which
one the official bucket uses: ``replica_cmds/<start_time>/<YYYYMMDD>/<start_height>`` (the
node's own) and ``replica_cmds/<YYYYMMDD>/<start_height>.lz4`` (third-party copies). Each
file holds 10,000 blocks; line ``i`` is block ``start_height + i + 1``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
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


def client(region: str = NODE_REGION) -> S3Client:
    # NOTE: imported here so the package and the server run without the aws extra.
    import boto3
    from botocore.config import Config

    return boto3.client("s3", region_name=region, config=Config(retries={"max_attempts": 5, "mode": "standard"}))


def fetcher(bucket: str, region: str) -> Callable[[str], bytes]:
    """``key -> bytes`` GET for one bucket; boto3's standard mode retries throttles and 5xx."""
    s3 = client(region)

    def fetch(key: str) -> bytes:
        return bytes(s3.get_object(Bucket=bucket, Key=key, **RP)["Body"].read())

    return fetch


@dataclass(frozen=True, slots=True)
class Obj:
    key: str
    size: int


def list_objects(s3: S3Client, prefix: str, bucket: str = NODE_BUCKET) -> Iterator[Obj]:
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix, **RP):
        for o in page.get("Contents", []):
            yield Obj(o["Key"], int(o["Size"]))


def list_prefixes(s3: S3Client, prefix: str, bucket: str = NODE_BUCKET) -> list[str]:
    """Immediate sub-"directories" of ``prefix`` (which should end in ``/``)."""
    pages = s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix, Delimiter="/", **RP)
    return [p["Prefix"] for page in pages for p in page.get("CommonPrefixes", [])]


def file_number(key: str) -> int:
    """``.../1191310000[.lz4]`` -> 1191310000 (a replica start height or a fills hour)."""
    return int(key.rsplit("/", 1)[-1].removesuffix(".lz4"))


def replica_day(s3: S3Client, day: str) -> list[Obj]:
    """All ``replica_cmds`` files for ``day`` (YYYYMMDD), either layout, sorted by start height."""
    top = list_prefixes(s3, "replica_cmds/")
    if f"replica_cmds/{day}/" in top:
        prefixes = [f"replica_cmds/{day}/"]
    else:
        prefixes = [f"{start}{day}/" for start in top if f"{start}{day}/" in list_prefixes(s3, start)]
    return sorted((o for p in prefixes for o in list_objects(s3, p)), key=lambda o: file_number(o.key))


def fills_day(s3: S3Client, day: str) -> list[Obj]:
    """``node_fills_by_block`` hourly files for ``day`` (YYYYMMDD), sorted by hour."""
    return sorted(list_objects(s3, f"node_fills_by_block/hourly/{day}/"), key=lambda o: file_number(o.key))


def download(s3: S3Client, key: str, dest: Path, bucket: str = NODE_BUCKET) -> Path:
    """Download one object unless an equal-size copy exists."""
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
