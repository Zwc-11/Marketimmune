"""What closing each segment's leftover positions would have cost (a sensitivity check).

usage: exit_cost.py OUT.csv TAKER_FEE_BPS RUN_SEG_DIR:RAW_DIR [RUN_SEG_DIR:RAW_DIR ...]

The paper runs mark every segment's end to the mid and start the next segment flat, so the cost of
closing is never paid. For each strategy and market: the position left at the segment's end (sum of
its fills), closed by a taker order walked through the last Hyperliquid book seen in that segment's
recording, plus the taker fee. Cost is against the mid, in $."""

import gzip
import json
import sys
from pathlib import Path

import pandas as pd


def last_books(raw: Path) -> dict[str, dict]:
    """The last l2Book per coin in the segment's last Hyperliquid file."""
    files = sorted(raw.glob("hl-*.log.gz"))
    books: dict[str, dict] = {}
    with gzip.open(files[-1], "rt") as f:
        try:
            for line in f:
                if '"l2Book"' not in line[:60] or not line.endswith("\n"):
                    continue
                data = json.loads(line.split("\t", 1)[1])["data"]
                books[data["coin"]] = data
        except EOFError:  # a recording cut by a stop: keep the whole lines
            pass
    return books


def walk(levels: list[dict], qty: float) -> float:
    """$ value of taking ``qty`` from these levels, best first; any remainder at the last level's price."""
    paid, left, px = 0.0, qty, None
    for lv in levels:
        px = float(lv["px"])
        take = min(left, float(lv["sz"]))
        paid += take * px
        left -= take
        if left <= 0:
            break
    if left > 0 and px is not None:
        paid += left * px
    return paid


def main() -> None:
    out, fee = sys.argv[1], float(sys.argv[2]) / 1e4
    rows = []
    for spec in sys.argv[3:]:
        seg, raw = (Path(p) for p in spec.split(":", 1))
        F = pd.read_json(seg / "fills.jsonl", lines=True)
        if F.empty:
            continue
        pos = (F.side * F.qty).groupby([F.strategy, F.coin]).sum()
        books = last_books(raw)
        for (strategy, coin), q in pos.items():
            if abs(q) < 1e-12 or coin not in books:
                continue
            bids, asks = books[coin]["levels"]
            mid = (float(bids[0]["px"]) + float(asks[0]["px"])) / 2
            # long: sell into the bids; short: buy from the asks
            paid = walk(bids if q > 0 else asks, abs(q))
            slip = abs(q) * mid - paid if q > 0 else paid - abs(q) * mid
            rows.append(
                {
                    "segment": seg.name,
                    "strategy": strategy,
                    "coin": coin,
                    "position_usd": q * mid,
                    "slippage_usd": slip,
                    "fee_usd": abs(q) * mid * fee,
                }
            )
    R = pd.DataFrame(rows)
    R["cost_usd"] = R.slippage_usd + R.fee_usd
    R.to_csv(out, index=False)
    S = R.groupby("strategy").agg(
        segments=("segment", "nunique"), gross_usd=("position_usd", lambda x: x.abs().sum()), cost_usd=("cost_usd", "sum")
    )
    S["bp_of_gross"] = (S.cost_usd / S.gross_usd * 1e4).round(1)
    print(S.round(2).to_string())


if __name__ == "__main__":
    main()
