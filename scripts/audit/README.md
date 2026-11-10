# Deep quotes on the audited engine, 2026-11-10 (exploratory)

Replays behind "The engine audit: the deep quotes replayed on corrected fills" in
`docs/research/paper-trading.md`; reports in `eval/paper/audit/`.

Run from a checkout of branch `audit/hip3-20261109` (the audited engine with `hush@`'s `k`).
`RAW` is the directory of the PC's `live-hip3` segments, `COINS` the 32 markets of
`eval/paper/hip3/coins_growth.txt`, and `S` the five settings:

    S="hush@d=8/quiet=0/tol=0.3,hush@d=12/quiet=0/tol=0.3,hush@d=12/quiet=0/k=10/tol=0.3,hush@d=8/quiet=0/k=10/tol=0.3,hush@d=8/quiet=0/k=6/tol=0.3"

- **Monday** (13.9 h, seven segments `seg-20261109T0129` to `seg-20261109T1334`):

      python -m marketimmune.cli.paper_tune --chain "mon=$RAW/seg-20261109T0129/raw,…,$RAW/seg-20261109T1334/raw" \
        --clock mon --causal-clock --config 250x4 --budget-usd 5000 --latency-ms 200 \
        --maker-fee-bps 0.3 --taker-fee-bps 0.9 --strategies "$S" --coins "$COINS" --work WORK --out mon_tune.json --md mon_tune.md
      python -m marketimmune.cli.paper_report --runs WORK/250x4/mon/seg-* --out mon_report.json

- **Sunday** (the cloud's 11.7 h recording), and again with `/stale=30` added to each setting:

      python -m marketimmune.cli.paper_trade --replay SUNDAY_RAW --out OUT --coins "$COINS" --strategies "$S" \
        --quote-usd 250 --max-quotes 4 --budget-usd 5000 --maker-fee-bps 0.3 --taker-fee-bps 0.9 --no-journal --latency-ms 200
      python -m marketimmune.cli.paper_report --runs OUT --out sun_report.json

- **Edge per fill:** `scripts/flow/edge.py STRATEGY 0.3 SEG_DIR…` on the same output directories.
- **`deep_audit.csv`:** one row per setting, the earlier engine's $ an hour (from
  `eval/paper/flow/variants.csv` and `sun_k12_report.json`) beside the audited engine's, with fills,
  filled $, the edge per fill and the orders and cancels per filled $ (the `actions` of each
  `summary.json` over the filled $).
