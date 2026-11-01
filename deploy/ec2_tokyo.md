# EC2 in Tokyo for the Hyperliquid and Hydromancer pulls

`hl-mainnet-node-data` (`replica_cmds`, `node_fills_by_block`, `misc_events_by_block`) and
`hydromancer-reservoir` (daily position snapshots) are requester-pays buckets in
**ap-northeast-1**. S3 to EC2 transfer inside that region costs nothing; the same
bytes downloaded to Canada cost ~$0.11/GB. So all raw processing runs on an
instance in Tokyo and only compact Parquet leaves the region.

What the buckets hold (listed from CloudShell, 2026-10-31):

| Data | Coverage | Size |
|---|---|---|
| `node_fills_by_block/hourly/<YYYYMMDD>/<H>.lz4` | 2025-07-27 to today | 0.44 GiB (2026-03-15) to 1.4 GiB (2025-10-10, 2026-10-15) a day |
| `replica_cmds/<restart time>/<YYYYMMDD>/<height>.lz4` (93 restart folders) | 2025-01-12 to today | 151 GiB (2026-03-15, 103 files) to 257 GiB (2026-10-15, 121 files) a day; each file is 10,000 blocks, 1.5 to 2.3 GiB |
| `hyperliquid-archive/market_data/<YYYYMMDD>/<H>/l2Book/<COIN>.lz4` (us-east-1) | 2023-04-15 to yesterday, uploaded weeks late | SOL 1.1 MiB an hour (2025-10) to 0.23 MiB (2026-10) |
| Hydromancer `global/snapshots/perp/all/date=YYYY-MM-DD/` | 2025-10-01 to 10-24, 2025-12-15 onward (none from 10-25 to 12-14) | 13.6 MiB a day |

## 1. Account (once)

1. Create the AWS account, turn on MFA for the root user, and stop using root:
   create an admin user through IAM Identity Center.
2. Billing → Budgets: a monthly cost budget at $25 with alerts at 50% and 100%.
3. Region selector: **Asia Pacific (Tokyo) ap-northeast-1** for everything below.

## 2. IAM role for the instance

Create a role `pop-ec2` (trusted entity: EC2) with `AmazonSSMManagedInstanceCore`
(so you connect with Session Manager and open no SSH port) and this inline policy.
Requester-pays reads need only `s3:GetObject` / `s3:ListBucket`; the request
itself must carry `RequestPayer=requester`, which `marketimmune.sources.hyperliquid_s3` always sends.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": "s3:ListBucket",
     "Resource": ["arn:aws:s3:::hl-mainnet-node-data", "arn:aws:s3:::hyperliquid-archive", "arn:aws:s3:::hydromancer-reservoir"]},
    {"Effect": "Allow", "Action": "s3:GetObject",
     "Resource": ["arn:aws:s3:::hl-mainnet-node-data/*", "arn:aws:s3:::hyperliquid-archive/*", "arn:aws:s3:::hydromancer-reservoir/*"]},
    {"Effect": "Allow", "Action": ["s3:ListBucket", "s3:GetObject", "s3:PutObject"],
     "Resource": ["arn:aws:s3:::pop-silver-CHANGEME", "arn:aws:s3:::pop-silver-CHANGEME/*"]}
  ]
}
```

`pop-silver-CHANGEME` is your own bucket (same region) for Parquet output.

## 3. Instance

- AMI: Ubuntu 24.04 LTS (x86_64).
- Type on the free plan (credits, no card charges): `c7i-flex.large` (2 vCPU, 4 GB, free-tier
  eligible) with a 100 GB gp3 root volume. The fill pull streams each file through memory,
  so it needs no local scratch. On the paid plan, an instance with local NVMe (e.g.
  `c6id.2xlarge`, 8 vCPU, 16 GB, ~474 GB NVMe) runs the `replica_cmds` extraction faster.
  Pass the hourly price to the probe as `--usd-per-hour`.
- Purchase option: on-demand on the free plan; Spot (one-time, interruption behaviour
  **terminate**) on the paid plan, where it is about a third of the price.
- IAM instance profile: `pop-ec2`. Security group: no inbound rules.

## 4. Run the probe

Connect with Session Manager, then:

```bash
sudo mkdir -p /data && sudo chown "$USER" /data   # on an NVMe instance: mkfs.ext4 /dev/nvme1n1 and mount it here
curl -LsSf https://astral.sh/uv/install.sh | sh && source ~/.local/bin/env
sudo snap install aws-cli --classic
git clone --branch redesign/exchange-terminal https://github.com/Zwc-11/MarketImmune.git && cd MarketImmune
uv sync --frozen --extra aws
uv run python -m marketimmune.cli.probe_s3_day --date 2025-12-15 --files 3 \
    --usd-per-hour <hourly price> --scratch /data/probe
```

Pick a December 2025 day first (it overlaps the Albers data), then repeat for one
pre-launch March 2026 day. The probe writes `results/probe_<date>.json` (counts and
distributions only) and raw examples to `data/logs/` (gitignored). Commit the JSON.

## 5. Pull fills and snapshots

```bash
uv run python -m marketimmune.cli.pull_snapshots --dates 20251215..20251231 --out /data/hydromancer
uv run python -m marketimmune.cli.pull_snapshots --dates 20251008..20251012 --out /data/hydromancer
uv run python -m marketimmune.cli.pull_node_fills --dates 20251008..20251012 --out /data/node_fills
uv run python -m marketimmune.cli.pull_node_fills --dates 20251201..20251231 --out /data/node_fills
uv run python -m marketimmune.cli.pull_node_fills --dates 20260301..20261031 --out /data/node_fills
aws s3 sync /data s3://pop-silver-CHANGEME/
```

Each pull prints a JSON line per day and skips days already written, so rerun it after a
spot interruption.

- **Memory.** The pull parses `--chunk-rows` legs (200,000) at a time and only for `--coins`.
  A synthetic day with 2M BTC legs, and as many legs of another coin in the same blocks, peaks
  at 0.58 GB.
  - The earlier version held a Python dict per leg of every coin for a whole day.
  - That version was killed for memory on busy days, even with one worker: 2025-10-10,
    2025-12-01 and 2026-03-02.
- **Workers.** `--workers 1` (the default) is enough. A day takes about 45 s
  (2025-12-15: 0.5 GiB read, 42.5 s).
- **Detaching.** Run long pulls with `setsid nohup ... &`: anything in the foreground of a
  Session Manager session stops when the session ends. The first day with a priority fee, per coin:

```bash
uv run python -c "import polars as pl; print(pl.scan_parquet('/data/node_fills/*/*.parquet').filter(pl.col('priority_gas') > 0).group_by('coin').agg(pl.col('block_time').min()).collect())"
```

On your machine, with a user that can read only `pop-silver-CHANGEME`:
`aws s3 sync s3://pop-silver-CHANGEME/node_fills data/bronze/node_fills` (and `hydromancer`).

## 6. Tear down

Terminate the instance when the run ends; its root volume goes with it (set
"Delete on termination", the default for root volumes). Check
Billing → Bills the next day: the probe should cost about a dollar of compute
plus cents of S3 requests.
