#!/bin/bash
# usage: majors.sh <total delay D ms | here> <coinbase extra ms>
# Replays the PC's 16 h live-optimized recording as a maker whose Hyperliquid feed arrives D/2 ms
# after each block and whose orders take D/2 ms, with Coinbase CB ms later than the PC saw it.
# "here": as recorded, 200 ms orders. Warm-up: the three PC segments before it (wallet scores, positions). Exploratory, not registered.
set -e
D=$1; CB=$2
if [ "$D" = here ]; then RT="--latency-ms 200"; else H=$((D / 2)); L=$((D - H)); RT="--retime hl=$H,cb=$CB --latency-ms $L"; fi
cd /home/claude/marketimmune
P=data/paper/pc; O=$P/opt
W="data/paper/fresh2/seg-20261107T1720/raw~,data/paper/fresh2/seg-20261107T1920/raw~,$P/live-mm/seg-20261107T2120/raw~"
T=$(for s in seg-20261107T2329 seg-20261108T0129 seg-20261108T0329 seg-20261108T0529 seg-20261108T0729 seg-20261108T0929 seg-20261108T1129 seg-20261108T1329; do echo -n "$O/$s/raw,"; done | sed 's/,$//')
N=D${D}_cb${CB}
S="touch,zgap@0.05,mm@1.5,mm@3,hush@d=3/quiet=5/inf=0.665/tol=0.3"
.venv/bin/python -m marketimmune.cli.paper_tune --chain "f=$W,$T" --clock f --causal-clock --config 250x4 --budget-usd 5000 \
  --strategies "$S" $RT --work data/paper/latency/$N \
  --out eval/paper/latency/majors_$N.json --md eval/paper/latency/majors_$N.md --jobs 1
R=$(for s in seg-20261107T2329 seg-20261108T0129 seg-20261108T0329 seg-20261108T0529 seg-20261108T0729 seg-20261108T0929 seg-20261108T1129 seg-20261108T1329; do echo -n "data/paper/latency/$N/250x4/f/$s "; done)
.venv/bin/python -m marketimmune.cli.paper_report --runs $R --out eval/paper/latency/majors_${N}_report.json --baseline touch > /dev/null
echo "done $N"
