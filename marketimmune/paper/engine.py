"""The paper engine: routes events to each coin's state and to every strategy instance, and writes
the run's fills, mids, equity curve, model log and feed delays.

With ``budget_usd``, each strategy is one account across the coins: a side that would take its gross
exposure (every position at its coin's mid, summed) past the budget is not quoted, and a taker does not
enter. Each coin runs every strategy named in ``strategies`` (``paper.strategies.quoter``; ``taker@<bps>``
for the gap taker). Instances do not
see each other: each one's orders face the real trades alone. Quantities are fixed at the first
Hyperliquid top of the run: ``quote_usd / mid``. Decisions are taken at most every ``EVAL_MS`` per
coin, on a new Hyperliquid top or a new Coinbase top.

With a ``journal`` (``paper.journal``), every side change, fill, taker decision, each coin's signals
every second and each instance's counters every minute are written as they happen. The journal only
reads: a run gives the same fills with or without it.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from marketimmune.logger import init_logger
from marketimmune.paper.checkpoint import execution_state, restore_execution
from marketimmune.paper.events import Depth, Event, RefTop, Top, Trade, valid_event
from marketimmune.paper.journal import SIGNAL_MS, Journal, context, num
from marketimmune.paper.maker import Maker, MarketMaker, mid_before, new_minute, risky, seen_size, sides_of
from marketimmune.paper.mm import Portfolio, info, is_mm, sweep_fill
from marketimmune.paper.orders import Account
from marketimmune.paper.signals import CoinState, Wallets
from marketimmune.paper.strategies import LIVE_STRATEGIES, quoter, taker_threshold

logger = init_logger(__name__)
BPS = 1e4
EVAL_MS = 20
SNAPSHOT_MS = 60_000

__all__ = ["Engine", "Taker", "Maker", "MarketMaker", "mid_before", "new_minute", "risky", "seen_size", "sides_of"]


class Taker:
    def __init__(
        self,
        name: str,
        threshold_bps: float,
        qty: float,
        latency_ms: int,
        fee_rate: float,
        hold_ms: int = 10_000,
        coin: str = "",
        journal: Journal | None = None,
    ) -> None:
        self.name = name
        self.coin = coin
        self.journal = journal
        self.minute = new_minute()
        self.ctx: dict[str, Any] | None = None  # signals at the pending decision
        self.threshold_bps = threshold_bps
        self.qty = qty
        self.latency_ms = latency_ms
        self.fee_rate = fee_rate
        self.hold_ms = hold_ms
        self.pending: tuple[int, int] | None = None  # side, block ms it reaches the book
        self.entered_ms: int | None = None  # local ms the entry fill was seen
        self.account = Account()
        self.depth_used: dict[tuple[int, int, float], float] = {}
        self.actions = 0

    def decide(self, coin: CoinState, local_ms: int, room: float = math.inf, ctx: dict[str, Any] | None = None) -> None:
        if self.pending is not None:
            return
        leg = None
        if self.account.position == 0:
            gap = coin.gap()
            if gap is not None and abs(gap) >= self.threshold_bps:
                if room >= self.qty:
                    self.pending = (1 if gap > 0 else -1, local_ms + self.latency_ms)
                    leg = "entry"
                else:
                    self.minute["budget"] += 1
        elif self.entered_ms is not None and local_ms - self.entered_ms >= self.hold_ms:
            self.pending = (-1 if self.account.position > 0 else 1, local_ms + self.latency_ms)
            leg = "exit"
        if leg is not None and self.pending is not None:
            self.actions += 1
            self.minute["orders"] += 1
            self.ctx = ctx
            if self.journal is not None:
                self.journal.write(
                    "taker", {"t": local_ms, "s": self.name, "c": self.coin, "leg": leg, "side": self.pending[0], "ctx": ctx}
                )

    def close_minute(self, local_ms: int) -> dict[str, Any]:
        out, self.minute = self.minute, new_minute()
        return out

    def on_top(self, ev: Top, local_ms: int, depth: Depth | None = None) -> None:
        if self.pending is None or min(ev.t_ms, local_ms) < self.pending[1]:
            return
        side = self.pending[0]
        closing = self.account.position != 0
        qty = abs(self.account.position) if closing else self.qty
        oldest = min(ev.t_ms, depth.t_ms) if depth is not None and 0 <= ev.t_ms - depth.t_ms <= 3000 else ev.t_ms
        self.depth_used = {key: value for key, value in self.depth_used.items() if key[0] >= oldest}
        px, qty = sweep_fill(ev, depth, side, qty, self.depth_used)
        self.pending = None
        if qty <= 0:
            return
        self.account.fill(ev.t_ms, side, px, qty, self.fee_rate)
        if abs(self.account.position) < 1e-9 * self.qty:
            self.account.position = 0.0  # float residue
        self.minute["fills"] += 1
        if self.journal is not None:
            self.journal.write(
                "fills",
                {
                    "t": local_ms,
                    "blk": ev.t_ms,
                    "s": self.name,
                    "c": self.coin,
                    "kind": "taker",
                    "leg": "exit" if closing else "entry",
                    "side": side,
                    "px": px,
                    "qty": num(qty, 8),
                    "fee": num(self.fee_rate * px * qty, 6),
                    "pos": num(self.account.position, 8),
                    "mid0": ev.mid,
                    "ctx": self.ctx,
                },
            )
        if self.account.position == 0:
            self.entered_ms = None
        elif not closing:
            self.entered_ms = local_ms


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
        sz_decimals: dict[str, int] | None = None,
        strategies: tuple[str, ...] = LIVE_STRATEGIES,
        budget_usd: float | None = None,
        journal: Journal | None = None,
        registered: tuple[str, ...] = (),
        twins: dict[str, str] | None = None,
    ) -> None:
        if not coins or len(set(coins)) != len(coins) or not strategies or len(set(strategies)) != len(strategies):
            raise ValueError("coins and strategies must be nonempty and unique")
        if not math.isfinite(quote_usd) or quote_usd <= 0 or latency_ms < 0 or max_quotes <= 0:
            raise ValueError("quote size and position limit must be positive; latency cannot be negative")
        if not all(math.isfinite(x) for x in (latency_ms, max_quotes, maker_fee_bps, taker_fee_bps)) or taker_fee_bps < 0:
            raise ValueError("latency, limits and fees must be finite; taker fee cannot be negative")
        if budget_usd is not None and (not math.isfinite(budget_usd) or budget_usd <= 0):
            raise ValueError("budget must be finite and positive")
        self.coins = coins
        # HIP-3 twins: a market whose reference is another market's book (``{"io:SNDK": "xyz:SNDK"}``)
        # instead of its own oracle; the gap's EWMA basis takes out the ratio between the two
        self.twins = dict(twins or {})
        self.twin_of: dict[str, list[str]] = {}
        for follower, leader in self.twins.items():
            self.twin_of.setdefault(leader, []).append(follower)
        self.registered = registered  # the strategies a pre-registration makes claims about (for the live view)
        self.journal = journal
        self.next_signal = 0
        self.clock: dict[str, Any] = {}  # the live clock correction (``paper.live.Clock.info``)
        self.strategies = strategies
        self.budget_usd = budget_usd
        self.by_strategy: dict[str, dict[str, Maker | Taker]] = {}
        self.latency_ms = latency_ms
        self.quote_usd = quote_usd
        self.max_quotes = max_quotes
        self.maker_fee = maker_fee_bps / BPS
        self.taker_fee = taker_fee_bps / BPS
        self.wallets = Wallets()
        self.states = {c: CoinState(c, self.wallets, (sz_decimals or {}).get(c)) for c in coins}
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
        self.seen: dict[str, int] = {}  # venue -> last receive ms of any of its events
        self.trade_ids: dict[tuple[str, int], None] = {}
        self.portfolios: dict[str, Portfolio] = {s: Portfolio(risky(s).p, self.seen) for s in strategies if is_mm(s)}

    def instances(self) -> list[tuple[str, Maker | Taker]]:
        out: list[tuple[str, Maker | Taker]] = []
        for coin in self.coins:
            out += [(coin, m) for m in self.makers.get(coin, [])] + [(coin, t) for t in self.takers.get(coin, [])]
        return out

    def _start_coin(self, coin: str, mid: float, qty: float | None = None) -> None:
        qty = self.quote_usd / mid if qty is None else qty
        decimals = self.states[coin].sz_decimals
        if decimals is not None:
            unit = 10**decimals
            qty = math.floor(qty * unit + 1e-10) / unit
        if qty <= 0:
            self.makers[coin], self.takers[coin] = [], []
            return
        makers = [n for n in self.strategies if taker_threshold(n) is None]
        self.makers[coin] = [
            MarketMaker(
                n,
                risky(n),
                qty,
                self.max_quotes * qty,
                self.latency_ms,
                self.maker_fee,
                self.taker_fee,
                self.portfolios[n],
                coin=coin,
                journal=self.journal,
            )
            if is_mm(n)
            else Maker(n, quoter(n), qty, self.max_quotes * qty, self.latency_ms, self.maker_fee, coin=coin, journal=self.journal)
            for n in makers
        ]
        self.takers[coin] = [
            Taker(n, t, qty, self.latency_ms, self.taker_fee, coin=coin, journal=self.journal)
            for n in self.strategies
            if (t := taker_threshold(n)) is not None
        ]
        instances: list[Maker | Taker] = [*self.makers[coin], *self.takers[coin]]
        for inst in instances:
            self.by_strategy.setdefault(inst.name, {})[coin] = inst

    def room(self, strategy: str, coin: str) -> float:
        """Coins of ``coin`` the strategy may still hold: its budget less its gross exposure in the other
        coins (each position at its coin's mid), over this coin's mid. Unlimited without a budget."""
        if self.budget_usd is None:
            return math.inf
        top = self.states[coin].top
        if top is None:
            return 0.0
        other = 0.0
        for c, inst in self.by_strategy.get(strategy, {}).items():
            t = self.states[c].top
            if c != coin and t is not None:
                exposure = inst.exposure() if isinstance(inst, Maker) else max(abs(inst.account.position), inst.qty if inst.pending else 0)
                other += exposure * t.mid
        return max(0.0, self.budget_usd - other) / top.mid

    def handle(self, ev: Event, local_ms: int) -> None:
        if not valid_event(ev) or not math.isfinite(local_ms) or local_ms < self.last_ms:
            return
        if isinstance(ev, RefTop) and ev.coin in self.twins and ev.bid == ev.ask:
            return  # a twin-referenced market ignores its own oracle
        if isinstance(ev, Top) and ev.coin in self.twin_of:
            for follower in self.twin_of[ev.coin]:
                self.handle(RefTop(follower, local_ms, ev.bid, ev.ask), local_ms)
        coin = self.states.get(ev.coin)
        if coin is None:
            return
        if isinstance(ev, Top) and coin.top is not None and ev.t_ms < coin.top.t_ms:
            return
        if isinstance(ev, Depth) and coin.depth is not None and ev.t_ms < coin.depth.t_ms:
            return
        if isinstance(ev, Trade):
            if coin.top is None or ev.t_ms < coin.top.t_ms:
                return
            if ev.tid is not None:
                key = (ev.coin, ev.tid)
                if key in self.trade_ids:
                    return
                self.trade_ids[key] = None
                if len(self.trade_ids) > 100_000:
                    self.trade_ids.pop(next(iter(self.trade_ids)))
        if self.started_ms is None:
            self.started_ms = local_ms
        self.last_ms = max(self.last_ms, local_ms)
        kind = type(ev).__name__
        self.counts[kind] = self.counts.get(kind, 0) + 1
        self.seen["cb" if isinstance(ev, RefTop) else "hl"] = local_ms
        if isinstance(ev, Top):
            if ev.coin not in self.makers:
                self._start_coin(ev.coin, ev.mid)
            coin.on_top(ev, local_ms)
            if self.counts[kind] % 50 == 0:
                self.lags["hl_top"].append(local_ms - ev.t_ms)
            for m in self.makers[ev.coin]:
                m.on_top(ev, local_ms)
            for t in self.takers[ev.coin]:
                t.on_top(ev, local_ms, coin.depth)
            self.evaluate(coin, local_ms)
        elif isinstance(ev, Depth):
            coin.on_depth(ev, local_ms)
            for m in self.makers.get(ev.coin, []):
                m.on_depth(ev, local_ms)
        elif isinstance(ev, Trade):
            coin.on_trade(ev, local_ms)
            if self.counts[kind] % 20 == 0:
                self.lags["hl_trade"].append(local_ms - ev.t_ms)
            for m in self.makers.get(ev.coin, []):
                m.on_trade(ev, coin, local_ms)
        elif isinstance(ev, RefTop):
            coin.on_ref(ev, local_ms)
            self.evaluate(coin, local_ms)

    def evaluate(self, coin: CoinState, local_ms: int) -> None:
        if coin.coin not in self.makers or local_ms - self.last_eval[coin.coin] < EVAL_MS:
            return
        self.last_eval[coin.coin] = local_ms
        ctx = context(coin, local_ms) if self.journal is not None else None
        for m in self.makers[coin.coin]:
            m.decide(coin, local_ms, self.room(m.name, coin.coin), ctx)
        for t in self.takers[coin.coin]:
            t.decide(coin, local_ms, self.room(t.name, coin.coin), ctx)

    def feed_gap(self, venue: str, local_ms: int, reason: str) -> None:
        self.gaps.append({"venue": venue, "t_ms": local_ms, "error": reason})
        self.seen.pop(venue, None)
        for name, state in self.states.items():
            if venue == "cb" and ":" in name:
                continue  # HIP-3 references arrive on Hyperliquid, not Coinbase
            if venue == "hl":
                state.book_received_ms = None
                state.pending.clear()
            else:
                state.ref_received_ms = None
            for maker in self.makers.get(name, []):
                for order in maker.orders:
                    order.t_cancel = min(order.t_cancel, local_ms + maker.latency_ms)
                maker.time_in_state(local_ms)
                maker.current = {1: None, -1: None}
                maker.sides = "none"

    def tick(self, local_ms: int) -> None:
        """Called every 100 ms: the model grid, and an equity snapshot every minute."""
        if not math.isfinite(local_ms) or local_ms < self.last_ms:
            return
        self.last_ms = local_ms
        for coin in self.states.values():
            coin.sample(local_ms)
        if self.portfolios:
            self.risk(local_ms)
        if self.journal is not None and local_ms >= self.next_signal:
            self.next_signal = local_ms - local_ms % SIGNAL_MS + SIGNAL_MS
            for c, st in self.states.items():
                if st.top is not None:
                    self.journal.write("signals", {"t": local_ms, "c": c, "blk": st.top.t_ms, **context(st, local_ms)})
        if local_ms >= self.next_snapshot:
            self.next_snapshot = local_ms + SNAPSHOT_MS
            self.snapshot(local_ms)

    def risk(self, local_ms: int) -> None:
        """Each ``mm`` strategy's equity and net dollars over its coins (the kill switch), and the dead
        man's switch when a feed is silent."""
        for name, port in self.portfolios.items():
            equity = net = 0.0
            for c, inst in self.by_strategy.get(name, {}).items():
                top = self.states[c].top
                if top is not None:
                    equity += inst.account.equity(top.mid)
                    net += inst.account.position * top.mid
            tripped = port.mark(local_ms, equity, net)
            if tripped and self.journal is not None:
                self.journal.write(
                    "decisions", {"t": local_ms, "s": name, "c": "*", "why": f"kill switch: equity {equity:+.2f}", "sides": "none"}
                )
            for c, inst in self.by_strategy.get(name, {}).items():
                if isinstance(inst, MarketMaker):
                    if tripped:
                        inst.decide(self.states[c], local_ms, self.room(name, c))
                    if not inst.fresh(self.states[c], local_ms):
                        inst.pull(local_ms + inst.latency_ms)

    def snapshot(self, local_ms: int) -> None:
        for coin, inst in self.instances():
            top = self.states[coin].top
            minute = inst.close_minute(local_ms)
            if top is None:
                continue
            a = inst.account
            if self.journal is not None:
                self.journal.write(
                    "minutes",
                    {
                        "t": local_ms,
                        "s": inst.name,
                        "c": coin,
                        **minute,
                        "pos_usd": num(a.position * top.mid, 2),
                        "equity": num(a.equity(top.mid), 4),
                    },
                )
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
        if self.journal is not None:
            self.journal.flush()

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
                    "actions": inst.actions,
                    "rejected_arrivals": inst.rejects if isinstance(inst, Maker) else 0,
                }
                | ({"exits": dict(inst.exits), "kills": inst.portfolio.kills} if isinstance(inst, MarketMaker) else {})
            )
        lags = {k: (np.percentile(v, [10, 50, 90]).round().tolist() if v else []) for k, v in self.lags.items()}
        return {
            "started_ms": self.started_ms,
            "last_ms": self.last_ms,
            "hours": round((self.last_ms - (self.started_ms if self.started_ms is not None else self.last_ms)) / 3.6e6, 3),
            "settings": {
                "latency_ms": self.latency_ms,
                "quote_usd": self.quote_usd,
                "max_quotes": self.max_quotes,
                "budget_usd": self.budget_usd,
                "strategies": list(self.strategies),
                "registered": list(self.registered),
                "mm": {name: info(port.p) for name, port in self.portfolios.items()},
            },
            "settings_fees_bps": {"maker": self.maker_fee * BPS, "taker": self.taker_fee * BPS},
            "counts": self.counts,
            "feed_delay_ms_p10_p50_p90": lags,
            "clock": self.clock,
            "connection_gaps": self.gaps,
            "models": {c: s.fit_log for c, s in self.states.items()},
            "instances": rows,
        }

    def write(self, out: Path, final: bool) -> None:
        out.mkdir(parents=True, exist_ok=True)
        summary_tmp = out / ".summary.json.tmp"
        summary_tmp.write_text(json.dumps(self.summary(), indent=1) + "\n", encoding="utf-8")
        summary_tmp.replace(out / "summary.json")
        if not final:
            return
        self.snapshot(self.last_ms)
        if self.journal is not None:
            self.journal.close()
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
        wallet_tmp = state_dir / ".wallets.json.tmp"
        wallet_tmp.write_text(json.dumps(self.wallets.state()), encoding="utf-8")
        wallet_tmp.replace(state_dir / "wallets.json")
        execution_tmp = state_dir / ".execution.json.tmp"
        execution_tmp.write_text(json.dumps(execution_state(self), allow_nan=False), encoding="utf-8")
        execution_tmp.replace(state_dir / "execution.json")
        for c, s in self.states.items():
            st = s.state()
            if st["rows"]:
                path = state_dir / f"{c.replace(':', '_')}.npz"
                temporary = path.with_suffix(".npz.tmp")
                with temporary.open("wb") as handle:
                    np.savez(
                        handle,
                        rows=np.asarray(st["rows"]),
                        row_ms=np.asarray(st["row_ms"]),
                        row_mid=np.asarray(st["row_mid"]),
                        basis=np.asarray([st["basis"]]),
                    )
                temporary.replace(path)

    def load_state(self, state_dir: Path) -> None:
        if (state_dir / "wallets.json").exists():
            self.wallets.load(json.loads((state_dir / "wallets.json").read_text(encoding="utf-8")))
        for c, s in self.states.items():
            path = state_dir / f"{c.replace(':', '_')}.npz"
            if path.exists():
                with np.load(path) as z:
                    s.load(
                        {
                            "rows": z["rows"].tolist(),
                            "row_ms": z["row_ms"].tolist(),
                            "row_mid": z["row_mid"].tolist(),
                            "basis": float(z["basis"][0]),
                        }
                    )
        execution = state_dir / "execution.json"
        if execution.exists():
            restore_execution(self, json.loads(execution.read_text(encoding="utf-8")))
        logger.info(f"loaded state from {state_dir}: {len(self.wallets.count)} wallets")
