"""What closing the positions held at the end of a chained replay would cost (audited engine).

usage: final_exit.py OUT.csv TAKER_FEE_BPS HOURS LAST_SEG_DIR RAW_DIR

The audited engine carries positions from one segment to the next, so only what is held at the
end of the last segment is never closed. Positions come from that segment's summary.json
(``position_usd`` of each strategy and market, valued at its last mid). Each is closed by a taker
order walked through the last Hyperliquid book in RAW_DIR, plus the taker fee; cost is against the
mid, in $. Writes one row per strategy: gross position, cost and cost an hour over HOURS."""

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "search"))

from exit_cost import last_books, walk  # noqa: E402


def main() -> None:
    out, fee, hours = sys.argv[1], float(sys.argv[2]) / 1e4, float(sys.argv[3])
    seg, raw = Path(sys.argv[4]), Path(sys.argv[5])
    books = last_books(raw)
    rows = []
    for inst in json.loads((seg / "summary.json").read_text())["instances"]:
        pos, coin = float(inst["position_usd"]), inst["coin"]
        if abs(pos) < 1e-9 or coin not in books:
            continue
        bids, asks = books[coin]["levels"]
        mid = (float(bids[0]["px"]) + float(asks[0]["px"])) / 2
        q = pos / mid
        paid = walk(bids if q > 0 else asks, abs(q))
        slip = abs(q) * mid - paid if q > 0 else paid - abs(q) * mid
        rows.append({"strategy": inst["strategy"], "coin": coin, "position_usd": pos, "cost_usd": slip + abs(pos) * fee})
    R = pd.DataFrame(rows)
    S = R.groupby("strategy").agg(gross_usd=("position_usd", lambda x: x.abs().sum()), cost_usd=("cost_usd", "sum"))
    S["per_hour"] = S.cost_usd / hours
    S.round(2).to_csv(out)
    print(S.round(2).to_string())


if __name__ == "__main__":
    main()
