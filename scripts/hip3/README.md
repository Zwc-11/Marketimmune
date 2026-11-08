# HIP-3 exploration helpers (2026-11-08)

Scratch analysis used for `docs/preregistration/paper-hip3-20261108.md`. They read and write under
`/tmp/hip3` (the cloud recording); `record_hip3.py` one level up is the recorder.

- `look.py`: spread, flow and per-trade maker markouts by market.
- `oracle.py`: how often each oracle moves and the mid-oracle gap.
- `twins.py`: lead-lag between markets on the same underlying.
- `wallets.py`: whether wallet scores from the majors predict HIP-3 takers.
- `grid.sh`, `summ.py`: replay a strategy list and tabulate it with both halves.
- `mk.py`: fill markouts at 1 s, 60 s, 5 min and 30 min, by market.
