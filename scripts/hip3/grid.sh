#!/bin/bash
# usage: grid.sh <name> <raw dir> <strategies file> [twins] [until_ms]
set -e
N=$1; RAW=$2; S=$(cat $3); TW=${4:-}; UNTIL=${5:-}
cd /home/claude/marketimmune
C=$(cat /tmp/hip3/coins_growth.txt)
rm -rf /tmp/hip3/$N
EXTRA=""; [ -n "$TW" ] && EXTRA="--twins $TW"; [ -n "$UNTIL" ] && EXTRA="$EXTRA --until-ms $UNTIL"
.venv/bin/python -m marketimmune.cli.paper_trade --replay $RAW --out /tmp/hip3/$N --coins "$C" --strategies "$S" --quote-usd 250 --max-quotes 4 --budget-usd 5000 --maker-fee-bps 0.3 --taker-fee-bps 0.9 --no-journal $EXTRA > /tmp/hip3/$N.log 2>&1
.venv/bin/python -m marketimmune.cli.paper_report --runs /tmp/hip3/$N --out /tmp/hip3/${N}_report.json --baseline touch > /dev/null 2>&1
.venv/bin/python -I /tmp/hip3/code/summ.py /tmp/hip3/$N
