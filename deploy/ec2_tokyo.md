# EC2 in Tokyo for `replica_cmds` (Phase 0)

`replica_cmds` sits in the requester-pays bucket `hl-mainnet-node-data` in
**ap-northeast-1**. S3 to EC2 transfer inside that region costs nothing; the same
bytes downloaded to Canada cost ~$0.11/GB. So all raw processing runs on a spot
instance in Tokyo and only compact Parquet leaves the region.

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
     "Resource": ["arn:aws:s3:::hl-mainnet-node-data", "arn:aws:s3:::hyperliquid-archive"]},
    {"Effect": "Allow", "Action": "s3:GetObject",
     "Resource": ["arn:aws:s3:::hl-mainnet-node-data/*", "arn:aws:s3:::hyperliquid-archive/*"]},
    {"Effect": "Allow", "Action": ["s3:ListBucket", "s3:GetObject", "s3:PutObject"],
     "Resource": ["arn:aws:s3:::pop-silver-CHANGEME", "arn:aws:s3:::pop-silver-CHANGEME/*"]}
  ]
}
```

`pop-silver-CHANGEME` is your own bucket (same region) for Parquet output.

## 3. Spot instance

- AMI: Ubuntu 24.04 LTS (x86_64).
- Type: one with local NVMe so files stream to fast scratch, e.g. `c6id.2xlarge`
  (8 vCPU, 16 GB, ~474 GB NVMe) for the probe; scale up for full extraction once
  the Rust extractor exists. Check the current spot price in the console and
  pass it to the probe as `--usd-per-hour`.
- Purchase option: Spot, one-time, interruption behaviour **terminate**.
- IAM instance profile: `pop-ec2`. Security group: no inbound rules.

## 4. Run the probe

Connect with Session Manager, then:

```bash
sudo mkfs.ext4 -F /dev/nvme1n1 && sudo mkdir -p /mnt/nvme && sudo mount /dev/nvme1n1 /mnt/nvme
sudo chown "$USER" /mnt/nvme
curl -LsSf https://astral.sh/uv/install.sh | sh && source ~/.local/bin/env
sudo snap install aws-cli --classic        # for the bulk fills copy below
git clone https://github.com/Zwc-11/MarketImmune.git && cd MarketImmune
uv sync --frozen --extra aws
uv run python -m marketimmune.cli.probe_s3_day --date 2025-12-15 --files 3 \
    --usd-per-hour <spot price> --scratch /mnt/nvme/probe
```

Pick a December 2025 day first (it overlaps the Albers data), then repeat for one
pre-launch March 2026 day. The probe writes `results/probe_<date>.json` (counts and
distributions only) and raw examples to `data/logs/` (gitignored). Commit the JSON.

The priority-fee launch scan downloads `node_fills_by_block` (~0.9 GB/day):

```bash
for d in $(seq 0 30); do day=$(date -u -d "2026-03-01 + $d day" +%Y%m%d); \
  aws s3 cp --recursive --request-payer requester \
    s3://hl-mainnet-node-data/node_fills_by_block/hourly/$day/ /mnt/nvme/fills/$day/; done
uv run python -m marketimmune.cli.find_first_priority_day first-priority --coin BTC /mnt/nvme/fills
```

(If the probe reports the flat layout, drop `hourly/` from the prefix.)

## 5. Tear down

Terminate the instance when the run ends; spot volumes go with it. Check
Billing → Bills the next day: the probe should cost about a dollar of compute
plus cents of S3 requests.
