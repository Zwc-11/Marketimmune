#!/bin/bash
cd /home/claude/marketimmune
G="/mnt/user-data/uploads/Crypto Data/paper"
for r in live live-tuned live-mm live-hush live-optimized-20261107T192854Z live-hip3; do
  segs=()
  for s in "$G/$r"/seg-*; do [ -f "$s/fills.jsonl" ] && [ -f "$s/mids.parquet" ] && segs+=("$s"); done
  .venv/bin/python -m marketimmune.cli.paper_report --runs "${segs[@]}" --out /tmp/loss/report_$r.json > /tmp/loss/report_$r.log 2>&1 &
done
wait
ls -la /tmp/loss/
