# HIP-3 search, 2026-11-09 (exploratory)

Replays behind "Searching the deep quotes" in `docs/research/paper-trading.md`; reports in
`eval/paper/search/`.

- **Selection data:** the cloud's Sunday HIP-3 recording, `/tmp/hip3/raw`, 32 markets,
  00:24–12:05 UTC on 8 November.
- **Check data:** the PC's `live-hip3` segments `seg-20261108T1219` and `seg-20261108T1420`
  (12:19–16:20 UTC, hours the cloud recording does not cover).
- `halves.py RUN...` gives $ an hour by strategy and market in each half of a run, from
  `equity.jsonl`.

Each replay is `paper_trade --replay` (or `paper_tune` for the PC check) at $250 × 4, a $5,000
budget, 200 ms and 0.3 / 0.9 bp. The strategy lists are in the reports.
