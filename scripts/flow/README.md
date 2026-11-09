# Flow studies, 2026-11-09 (exploratory)

Scripts behind "Why the deep quotes lose on weekdays, and three ideas tested" in
`docs/research/paper-trading.md`; outputs in `eval/paper/flow/`.

- `prints.py OUT_DIR NAME=RAW_DIR …`: every public trade print of a recording (both wallets, the
  zero-hash flag) and the best bid/ask series.
- `twap.py PRINTS_DIR OUT_PREFIX`: TWAP slices (zero-hash prints), maker markouts by flow class,
  TWAP sizes, drift and the net-TWAP signal.
- `study.py PRINTS_DIR OUT_PREFIX [MAKER_FEE TAKER_FEE]`: maker markouts by hour, the largest
  makers, the just-in-time quote test and the TWAP-follow test.
- `ourfills.py PRINTS_DIR STRATEGY NAME=SEG_DIR …`: our paper fills against the true mid just
  before the print that caused them.
- `edge.py STRATEGY FEE_BPS SEG_DIR …`: the edge per fill (60 s markout minus the fee) with a
  block-bootstrap interval. This is P1 of the two registrations of 2026-11-09.

The print and quote files themselves are large and are not in the repository; rebuild them with
`prints.py` from the raw recordings.
