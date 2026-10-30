"""First day with a nonzero priority fee for a coin in local node_fills_by_block files.

    python -m marketimmune.cli.find_first_priority_day first-priority --coin BTC \
        data/bronze/node_fills_by_block"""

from marketimmune.priority.fills import main

if __name__ == "__main__":
    raise SystemExit(main())
