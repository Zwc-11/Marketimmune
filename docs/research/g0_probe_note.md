# Gate G0 note

Phase 0 ends when this page answers four questions. Each answer cites the probe
JSON in `eval/` that supports it. Status on 2026-10-30: **open**; nothing has
been run against the official bucket yet (needs the AWS account, deploy/ec2_tokyo.md).

| # | Question | Answer | Evidence |
| - | -------- | ------ | -------- |
| 1 | Are responses (`resps`) in `replica_cmds`, with order ids? | TBD | `eval/probe_<date>.json` → `q1_*` |
| 2 | What does one processed day cost? | TBD | `q2_one_day` (Python prototype; re-measure with the Rust extractor) |
| 3 | Which dates can E1 use? | TBD (follows from 1) | `q3_e1_dates` |
| 4 | When did priority fees reach core perps? | TBD | `python -m marketimmune.priority.fills first-priority --coin BTC` over Mar–Jun 2026 |

## What is already known (before the probe)

- **A third-party copy of `replica_cmds` carries responses.** Dwellir's catalogue
  documents `resps.Full`, aligned with `signed_action_bundles`, each result with
  `res.status`, `res.response` (order statuses such as `resting` / `filled` with
  oids) and a `user` field. If the official files match, (a) every resting order's
  oid links to the action that placed it, so E1 can use any date, and (b) `user`
  may give the account directly, which would turn signer recovery (Lesson 3.2)
  into a validation step instead of a requirement. The probe measures both
  (`q1_share_orders_with_oid`, `resps.results_with_user`).
- **File layout is not settled.** Dwellir shows `replica_cmds/<YYYYMMDD>/<start>.lz4`;
  the node writes `replica_cmds/<start_time>/<YYYYMMDD>/<start>`. `marketimmune.sources.hyperliquid_s3`
  handles both; the probe records which one the official bucket uses.
- **Albers book diffs have no timestamps or block heights.** Each record is user,
  oid, coin, side, px and new/remove/update, in sequence, hourly files. Block
  assignment for outcome mode has to come from joining each diff to its
  order-status event (`open` → `new`, `filled`/`canceled` → `remove`/`update`),
  whose `ts` is in nanoseconds. That join is the first Phase 1 task; its match
  rate goes in the data card.
- **Failed snipes are in the "rejected" order-status files.** An IOC that finds
  nothing to hit ends as `iocCancelRejected`; the Albers README puts rejected
  orders (~89% of submissions) only in the order-status data, never in book
  diffs. That is why the download includes the 78 GB of rejected files.
- **`priorityGas` units are unverified.** Orders carry `grouping.p` (rate,
  p/1e8 of notional); fills carry `priorityGas`, which may be the same rate or the
  amount burned. Compare the two on matched oids before converting to bps.
- **Albers download:** 165.9 GB (orders + rejected for BTC/ETH/SOL, book diffs,
  mapdir) runs on the local machine with `marketimmune/sources/albers_download.py`; md5 checked
  per file, `data/bronze/albers/MANIFEST.json` records what is verified.
- **Binance aggTrades:** daily zips are sha256-verified on download. BTCUSDT on
  2025-12-15 is 27 MB, so every needed day for three coins is a few GB.

## Decision once answered

- If Q1 is yes: E1 windows = Dec 2025 + two pre-launch weeks in March 2026 + a
  post-launch window starting at Q4's date. Set them in `configs/data.yaml`.
- If Q1 is no: E1 rests on Dec 2025 (Albers) plus, if bought, Dwellir order
  statuses from 2026-01-22; record the cost of that option here before deciding.
