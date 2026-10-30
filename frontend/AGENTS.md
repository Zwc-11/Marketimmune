# MarketImmune frontend guide

The visual and engineering contract for the web app lives in
[DESIGN.md](DESIGN.md). Read it before changing anything under `frontend/`.

Quick rules:

- Exchange terminal conventions (Hyperliquid, Phoenix): dark, dense, tabular
  numbers, green and red only for side or outcome.
- Live data comes straight from Hyperliquid's public API; model numbers come from
  `eval/markout_sol_10s/` or the Django API. Never add simulated market data.
- Keep `src/lib/*` in parity with the Python features and model; regenerate the
  fixtures with `python -m marketimmune.cli.make_parity_fixtures` and run
  `npm test` in `frontend/`.
- Every source file stays under 1000 lines (`python scripts/check_line_limit.py`).
