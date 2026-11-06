"""The paper engine: routes events to each coin's state and to every strategy instance, and writes
the run's fills, mids, equity curve, model log and feed delays.

Each coin runs every strategy in ``maker_quoters`` and every ``GapTaker`` threshold. Instances do not
see each other: each one's orders face the real trades alone. Quantities are fixed at the first
Hyperliquid top of the run: ``quote_usd / mid``. Decisions are taken at most every ``EVAL_MS`` per
coin, on a new Hyperliquid top or a new Coinbase top.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from marketimmune.logger import init_logger
from marketimmune.paper.events import Depth, Event, RefTop, Top, Trade
from marketimmune.paper.orders import Account, PaperOrder
from marketimmune.paper.signals import CoinState, Wallets
from marketimmune.paper.strategies import TAKER_THRESHOLDS_BPS, Quoter, maker_quoters

logger = init_logger(__name__)
BPS = 1e4
EVAL_MS = 20
SNAPSHOT_MS = 60_000


class Maker:
    def __init__(self, name: str, quoter: Quoter, qty: float, max_position: float, latency_ms: int, fee_rate: float) -> None:
        self.name = name
        self.quoter = quoter
        self.qty = qty
        self.max_position = max_position
        self.latency_ms = latency_ms
        self.fee_rate = fee_rate
        self.orders: list[PaperOrder] = []
        self.current: dict[int, PaperOrder | None] = {1: None, -1: None}
        self.account = Account()

    def decide(self, coin: CoinState, local_ms: int) -> None:
        bid, ask = self.quoter.quotes(coin, local_ms, self.account.position, self.max_position)
        for side, px in ((1, bid), (-1, ask)):
            cur = self.current[side]
            if cur is not None and (px is None or cur.px != px or cur.qty <= 0):
                cur.t_cancel = min(cur.t_cancel, local_ms + self.latency_ms)
                cur = self.current[side] = None
            if px is not None and cur is None:
                order = PaperOrder(side, px, self.qty, local_ms + self.latency_ms)
                self.orders.append(order)
                self.current[side] = order

    def on_top(self, ev: Top) -> None:
        self.orders = [o for o in self.orders if o.qty > 0 and o.t_cancel > ev.t_ms]
        for o in self.orders:
            if o.side > 0 and o.px >= ev.bid:
                o.see_level(ev.t_ms, ev.bid_sz if o.px == ev.bid else 0.0)
            elif o.side < 0 and o.px <= ev.ask:
                o.see_level(ev.t_ms, ev.ask_sz if o.px == ev.ask else 0.0)

    def on_depth(self, ev: Depth) -> None:
        for o in self.orders:
            levels = ev.bids if o.side > 0 else ev.asks
            if not levels:
                continue
            best = max(levels) if o.side > 0 else min(levels)
            if (o.px > best) if o.side > 0 else (o.px < best):
                o.see_level(ev.t_ms, 0.0)
            elif o.px in levels:
                o.see_level(ev.t_ms, levels[o.px])

    def on_trade(self, ev: Trade, coin: CoinState) -> None:
        for o in self.orders:
            q = o.match(ev.t_ms, ev.px, ev.sz, ev.taker_buy, seen_size(coin, o))
            if q > 0:
                self.account.fill(ev.t_ms, o.side, o.px, q, self.fee_rate)
        self.orders = [o for o in self.orders if o.qty > 0 and o.t_cancel > ev.t_ms]


def seen_size(coin: CoinState, o: PaperOrder) -> float:
    """The latest seen size at an order's price: the top's, else the depth's, else 0."""
    top = coin.top
    if top is not None:
        if o.side > 0 and o.px >= top.bid:
            return top.bid_sz if o.px == top.bid else 0.0
        if o.side < 0 and o.px <= top.ask:
            return top.ask_sz if o.px == top.ask else 0.0
    if coin.depth is not None:
        return (coin.depth.bids if o.side > 0 else coin.depth.asks).get(o.px, 0.0)
    return 0.0


class Taker:
    def __init__(self, name: str, threshold_bps: float, qty: float, latency_ms: int, fee_rate: float, hold_ms: int = 10_000) -> None:
        self.name = name
        self.threshold_bps = threshold_bps
        self.qty = qty
        self.latency_ms = latency_ms
        self.fee_rate = fee_rate
        self.hold_ms = hold_ms
        self.pending: tuple[int, int] | None = None  # side, block ms it reaches the book
        self.entered_ms: int | None = None  # local ms the entry fill was seen
        self.account = Account()

    def decide(self, coin: CoinState, local_ms: int) -> None:
        if self.pending is not None:
            return
        if self.account.position == 0:
            gap = coin.gap()
            if gap is not None and abs(gap) >= self.threshold_bps:
                self.pending = (1 if gap > 0 else -1, local_ms + self.latency_ms)
        elif self.entered_ms is not None and local_ms - self.entered_ms >= self.hold_ms:
            self.pending = (-1 if self.account.position > 0 else 1, local_ms + self.latency_ms)

    def on_top(self, ev: Top, local_ms: int) -> None:
        if self.pending is None or ev.t_ms < self.pending[1]:
            return
        side = self.pending[0]
        closing = self.account.position != 0
        qty = abs(self.account.position) if closing else self.qty
        self.account.fill(ev.t_ms, side, ev.ask if side > 0 else ev.bid, qty, self.fee_rate)
        if closing:
            self.account.position = 0.0  # float residue
        self.entered_ms = None if closing else local_ms
        self.pending = None


class Engine:
    def __init__(
        self,
        coins: tuple[str, ...],
        *,
        latency_ms: int = 200,
        quote_usd: float = 1_000.0,
        max_quotes: int = 5,
        maker_fee_bps: float = 1.5,
        taker_fee_bps: float = 4.5,
    ) -> None:
        self.coins = coins
        self.latency_ms = latency_ms
        self.quote_usd = quote_usd
        self.max_quotes = max_quotes
        self.maker_fee = maker_fee_bps / BPS
        self.taker_fee = taker_fee_bps / BPS
        self.wallets = Wallets()
        self.states = {c: CoinState(c, self.wallets) for c in coins}
        self.makers: dict[str, list[Maker]] = {}
        self.takers: dict[str, list[Taker]] = {}
        self.last_eval: dict[str, int] = dict.fromkeys(coins, 0)
        self.next_snapshot = 0
        self.snapshots: list[dict[str, Any]] = []
        self.lags: dict[str, list[int]] = {"hl_top": [], "hl_trade": []}
        self.counts: dict[str, int] = {}
        self.gaps: list[dict[str, Any]] = []
        self.started_ms: int | None = None
        self.last_ms = 0

    def instances(self) -> list[tuple[str, Maker | Taker]]:
        out: list[tuple[str, Maker | Taker]] = []
        for coin in self.coins:
            out += [(coin, m) for m in self.makers.get(coin, [])] + [(coin, t) for t in self.takers.get(coin, [])]
        return out

    def _start_coin(self, coin: str, mid: float) -> None:
        qty = self.quote_usd / mid
        self.makers[coin] = [Maker(n, q, qty, self.max_quotes * qty, self.latency_ms, self.maker_fee) for n, q in maker_quoters().items()]
        self.takers[coin] = [Taker(n, t, qty, self.latency_ms, self.taker_fee) for n, t in TAKER_THRESHOLDS_BPS.items()]

    def handle(self, ev: Event, local_ms: int) -> None:
        coin = self.states.get(ev.coin)
        if coin is None:
            return
        self.started_ms = self.started_ms or local_ms
        self.last_ms = max(self.last_ms, local_ms)
        kind = type(ev).__name__
        self.counts[kind] = self.counts.get(kind, 0) + 1
        if isinstance(ev, Top):
            if ev.coin not in self.makers:
                self._start_coin(ev.coin, ev.mid)
            coin.on_top(ev, local_ms)
            if self.counts[kind] % 50 == 0:
                self.lags["hl_top"].append(local_ms - ev.t_ms)
            for m in self.makers[ev.coin]:
                m.on_top(ev)
            for t in self.takers[ev.coin]:
                t.on_top(ev, local_ms)
            self.evaluate(coin, local_ms)
        elif isinstance(ev, Depth):
            coin.on_depth(ev)
            for m in self.makers.get(ev.coin, []):
                m.on_depth(ev)
        elif isinstance(ev, Trade):
            coin.on_trade(ev, local_ms)
            if self.counts[kind] % 20 == 0:
                self.lags["hl_trade"].append(local_ms - ev.t_ms)
            for m in self.makers.get(ev.coin, []):
                m.on_trade(ev, coin)
        elif isinstance(ev, RefTop):
            coin.on_ref(ev, local_ms)
            self.evaluate(coin, local_ms)

    def evaluate(self, coin: CoinState, local_ms: int) -> None:
        if coin.coin not in self.makers or local_ms - self.last_eval[coin.coin] < EVAL_MS:
            return
        self.last_eval[coin.coin] = local_ms
        for m in self.makers[coin.coin]:
            m.decide(coin, local_ms)
        for t in self.takers[coin.coin]:
            t.decide(coin, local_ms)

    def tick(self, local_ms: int) -> None:
        """Called every 100 ms: the model grid, and an equity snapshot every minute."""
        for coin in self.states.values():
            coin.sample(local_ms)
        if local_ms >= self.next_snapshot:
            self.next_snapshot = local_ms + SNAPSHOT_MS
            self.snapshot(local_ms)

    def snapshot(self, local_ms: int) -> None:
        for coin, inst in self.instances():
            top = self.states[coin].top
            if top is None:
                continue
            a = inst.account
            self.snapshots.append(
                {
                    "t_ms": local_ms,
                    "coin": coin,
                    "strategy": inst.name,
                    "equity": a.equity(top.mid),
                    "position_usd": a.position * top.mid,
                    "fills": a.fills,
                    "notional": a.notional,
                    "fees": a.fees,
                }
            )

    # --- output
    def summary(self) -> dict[str, Any]:
        rows = []
        for coin, inst in self.instances():
            top = self.states[coin].top
            a = inst.account
            rows.append(
                {
                    "coin": coin,
                    "strategy": inst.name,
                    "fills": a.fills,
                    "notional": round(a.notional, 2),
                    "fees": round(a.fees, 4),
                    "equity": round(a.equity(top.mid), 4) if top else 0.0,
                    "position_usd": round(a.position * top.mid, 2) if top else 0.0,
                }
            )
        lags = {k: (np.percentile(v, [10, 50, 90]).round().tolist() if v else []) for k, v in self.lags.items()}
        return {
            "started_ms": self.started_ms,
            "last_ms": self.last_ms,
            "hours": round((self.last_ms - (self.started_ms or self.last_ms)) / 3.6e6, 3),
            "settings": {"latency_ms": self.latency_ms, "quote_usd": self.quote_usd, "max_quotes": self.max_quotes},
            "settings_fees_bps": {"maker": self.maker_fee * BPS, "taker": self.taker_fee * BPS},
            "counts": self.counts,
            "feed_delay_ms_p10_p50_p90": lags,
            "connection_gaps": self.gaps,
            "models": {c: s.fit_log for c, s in self.states.items()},
            "instances": rows,
        }

    def write(self, out: Path, final: bool) -> None:
        out.mkdir(parents=True, exist_ok=True)
        (out / "summary.json").write_text(json.dumps(self.summary(), indent=1) + "\n", encoding="utf-8")
        if not final:
            return
        self.snapshot(self.last_ms)
        (out / "equity.jsonl").write_text("".join(json.dumps(r) + "\n" for r in self.snapshots), encoding="utf-8")
        fills = [
            {"coin": c, "strategy": i.name, "t_ms": t, "side": s, "px": px, "qty": q, "fee_rate": f}
            for c, i in self.instances()
            for t, s, px, q, f in i.account.log
        ]
        (out / "fills.jsonl").write_text("".join(json.dumps(r) + "\n" for r in fills), encoding="utf-8")
        coins, ts, mids = [], [], []
        for c, s in self.states.items():
            coins += [c] * len(s.mids)
            ts += [t for t, _ in s.mids]
            mids += [m for _, m in s.mids]
        pq.write_table(
            pa.table({"coin": coins, "t_ms": pa.array(ts, pa.int64()), "mid": pa.array(mids, pa.float64())}), out / "mids.parquet"
        )
        logger.info(f"wrote {out}: {len(fills)} fills, {len(mids)} mids")

    def save_state(self, state_dir: Path) -> None:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "wallets.json").write_text(json.dumps(self.wallets.state()), encoding="utf-8")
        for c, s in self.states.items():
            st = s.state()
            if st["rows"]:
                np.savez(
                    state_dir / f"{c}.npz",
                    rows=np.asarray(st["rows"]),
                    row_ms=np.asarray(st["row_ms"]),
                    row_mid=np.asarray(st["row_mid"]),
                    basis=np.asarray([st["basis"]]),
                )

    def load_state(self, state_dir: Path, now_ms: int) -> None:
        if (state_dir / "wallets.json").exists():
            self.wallets.load(json.loads((state_dir / "wallets.json").read_text(encoding="utf-8")))
        for c, s in self.states.items():
            path = state_dir / f"{c}.npz"
            if path.exists():
                z = np.load(path)
                s.load(
                    {
                        "rows": z["rows"].tolist(),
                        "row_ms": z["row_ms"].tolist(),
                        "row_mid": z["row_mid"].tolist(),
                        "basis": float(z["basis"][0]),
                    },
                    now_ms,
                )
        logger.info(f"loaded state from {state_dir}: {len(self.wallets.count)} wallets")
