"""Carry inventory between recording segments without inventing a closing trade.

Each segment reports incremental PnL. Carried cash is rebased to the last mark,
while inventory, entry prices and portfolio drawdown thresholds remain exposed.
Orders are cancelled with latency at the recording boundary; the next segment
records the feed gap and retains their reservation until exchange time advances.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from marketimmune.paper.events import Top
from marketimmune.paper.maker import Maker, MarketMaker
from marketimmune.paper.orders import PaperOrder

if TYPE_CHECKING:
    from marketimmune.paper.engine import Engine


def configuration(engine: Engine) -> dict[str, Any]:
    summary = engine.summary()
    return {"coins": list(engine.coins), "twins": engine.twins, "settings": summary["settings"], "fees": summary["settings_fees_bps"]}


def execution_state(engine: Engine) -> dict[str, Any]:
    rows = []
    equity: dict[str, float] = {}
    for coin, instance in engine.instances():
        top = engine.states[coin].top
        if top is None:
            continue
        equity[instance.name] = equity.get(instance.name, 0.0) + instance.account.equity(top.mid)
        row: dict[str, Any] = {"coin": coin, "strategy": instance.name, "qty": instance.qty, "position": instance.account.position}
        if isinstance(instance, Maker):
            row["orders"] = [
                asdict(order) | {"t_cancel": min(order.t_cancel, engine.last_ms + instance.latency_ms)}
                for order in instance.orders
                if order.qty > 0
            ]
            if isinstance(instance, MarketMaker):
                row["risk"] = {
                    key: getattr(instance, key)
                    for key in ("entry", "opened_ms", "pending", "exit_qty", "pending_ctx", "cool_until", "last_ms")
                }
                row["used"] = [[*key, value] for key, value in instance.exit_used.items()]
        else:
            row["pending"] = instance.pending
            row["entered_ms"] = instance.entered_ms
            row["ctx"] = instance.ctx
            row["used"] = [[*key, value] for key, value in instance.depth_used.items()]
        rows.append(row)
    portfolios = {
        name: {
            "peak": None if port.peak is None else port.peak - equity.get(name, 0.0),
            "paused_until": port.paused_until,
            "kills": port.kills,
        }
        for name, port in engine.portfolios.items()
    }
    return {
        "version": 1,
        "config": configuration(engine),
        "last_ms": engine.last_ms,
        "tops": {coin: asdict(state.top) for coin, state in engine.states.items() if state.top is not None},
        "instances": rows,
        "portfolios": portfolios,
        "trade_ids": list(engine.trade_ids),
    }


def restore_execution(engine: Engine, state: dict[str, Any]) -> None:
    if state.get("version") != 1 or state["config"] != configuration(engine):
        raise ValueError("Execution checkpoint configuration differs; use a new state directory for a new experiment")
    engine.last_ms = state["last_ms"]
    for coin, values in state["tops"].items():
        saved_top = Top(**values)
        engine.states[coin].top = saved_top  # valuation only: receipt freshness remains unknown
        engine._start_coin(coin, saved_top.mid, qty=next((row["qty"] for row in state["instances"] if row["coin"] == coin), 0.0))
    for row in state["instances"]:
        instance = engine.by_strategy[row["strategy"]][row["coin"]]
        top = engine.states[row["coin"]].top
        if top is None:
            raise ValueError("Execution checkpoint inventory has no valuation book")
        instance.account.position = row["position"]
        instance.account.cash = -row["position"] * top.mid
        used = {(int(t), int(side), float(px)): float(qty) for t, side, px, qty in row.get("used", [])}
        if isinstance(instance, Maker):
            instance.orders = [PaperOrder(**values) for values in row["orders"]]
            if isinstance(instance, MarketMaker):
                for key, value in row["risk"].items():
                    setattr(instance, key, tuple(value) if key == "pending" and value is not None else value)
                instance.tracked = instance.account.position
                instance.exit_used = used
                instance.state = engine.states[row["coin"]]
        else:
            instance.pending = tuple(row["pending"]) if row["pending"] is not None else None
            instance.entered_ms = row["entered_ms"]
            instance.ctx = row["ctx"]
            instance.depth_used = used
    for name, values in state["portfolios"].items():
        port = engine.portfolios[name]
        port.peak, port.paused_until, port.kills = values["peak"], values["paused_until"], values["kills"]
    engine.trade_ids = {tuple(key): None for key in state["trade_ids"]}
    if state["tops"]:
        engine.gaps.append(
            {
                "venue": "hl",
                "t_ms": engine.last_ms,
                "error": "recording boundary: inventory retained; outstanding quotes cancelled with latency",
            }
        )
