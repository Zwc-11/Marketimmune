"""First day with a nonzero priority fee for a coin in local ``node_fills_by_block`` files.

python -m marketimmune.cli.find_first_priority_day first-priority --coin BTC data/bronze/node_fills_by_block
"""

from __future__ import annotations

import argparse
from pathlib import Path

from marketimmune.priority.fills import first_priority_day, local_days


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    fp = sub.add_parser("first-priority", help="first day priorityGas > 0 appears for a coin")
    fp.add_argument("root", type=Path, help="directory holding <YYYYMMDD>/<hour>.lz4 files")
    fp.add_argument("--coin", default="BTC")
    args = ap.parse_args(argv)
    # Only blocks that carry a priorityGas field can hit, so skip the rest before JSON.
    day = first_priority_day(local_days(args.root, contains='"priorityGas"'), args.coin)
    print(day.isoformat() if day else f"no priorityGas > 0 on {args.coin} in {args.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
