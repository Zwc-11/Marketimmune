#!/bin/bash
# usage: hip3.sh <total delay D ms | here>
# Replays the cloud's 11.7 h HIP-3 recording (32 growth-mode perps, fees 0.3 / 0.9 bp) as a maker whose
# feed arrives D/2 ms after each block and whose orders take D/2 ms; "here" = as recorded, 200 ms orders.
set -e
D=$1; cd /home/claude/marketimmune
C=$(cat /tmp/hip3/coins_growth.txt)
S="touch,zgap@0.05,mm@3,mm@8,hush@d=1/quiet=5/tol=0.3,hush@d=8/quiet=0/tol=0.3"
if [ "$D" = here ]; then EXTRA="--latency-ms 200"; else H=$((D / 2)); L=$((D - H)); EXTRA="--retime hl=$H,cb=0 --latency-ms $L"; fi
OUT=data/paper/latency/hip3_$D; rm -rf $OUT
.venv/bin/python -m marketimmune.cli.paper_trade --replay /tmp/hip3/raw --out $OUT --coins "$C" --strategies "$S" \
  --quote-usd 250 --max-quotes 4 --budget-usd 5000 --maker-fee-bps 0.3 --taker-fee-bps 0.9 --no-journal $EXTRA > $OUT.log 2>&1
.venv/bin/python -m marketimmune.cli.paper_report --runs $OUT --out eval/paper/latency/hip3_${D}_report.json --baseline touch > /dev/null
echo "done hip3 $D"
