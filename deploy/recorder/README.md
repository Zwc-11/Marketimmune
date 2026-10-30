# Recorder

Forward data from November 2026: Hyperliquid `l2Book`, `bbo`, `trades` for BTC,
ETH and SOL, and Binance USD-M `bookTicker`, each line stamped with local
receive time (`<local_ns> <raw_json>`). Read `docs/jurisdiction.md` first: the
open question there must be settled before this connects to live endpoints.

## VPS setup (Ubuntu 24.04, 1 vCPU / 1 GB is enough)

```bash
sudo apt-get update && sudo apt-get install -y chrony zstd python3.12-venv
sudo cp chrony.conf /etc/chrony/chrony.conf && sudo systemctl restart chrony
chronyc tracking            # "System time" offset should settle well under 1 ms

sudo useradd --system --home /var/lib/pop pop
sudo mkdir -p /opt/pop /var/lib/pop/recorder && sudo chown pop: /var/lib/pop/recorder
sudo cp -r . /opt/pop/recorder
sudo python3.12 -m venv /opt/pop/venv && sudo /opt/pop/venv/bin/pip install -r /opt/pop/recorder/requirements.txt

# smoke test: 60 s, then inspect the files and gaps.jsonl
sudo -u pop /opt/pop/venv/bin/python /opt/pop/recorder/record.py --out /var/lib/pop/recorder --max-seconds 60

sudo cp systemd/* /etc/systemd/system/ && sudo systemctl daemon-reload
sudo systemctl enable --now recorder.service recorder-rotate.timer
```

## Week-1 checks (Phase 0 gate)

- One file per venue per hour under `/var/lib/pop/recorder/<venue>/<YYYYMMDD>/`, older hours as `.log.zst`.
- `gaps.jsonl` has a `connected` line per (re)connect; force one with
  `sudo systemctl restart recorder` and confirm a `stopped` / `connected` pair.
- `stats.jsonl` message counts per minute are stable (no venue at zero).
- `chronyc tracking` offset logged daily alongside the data.

Pull data down with `rsync -av --include='*.zst' ...`; only compressed hours
are complete.
