"""The live view of a paper run: a page at ``http://127.0.0.1:<port>/`` that reads ``/state.json``
every second (``cli.paper_trade --serve <port>``).

``Board`` keeps what the page shows across segments:

- each strategy's PnL, fills, filled notional, gross position and order actions, summed over the
  coins (finished segments plus the running one);
- a PnL history every 10 s;
- each coin's mid, spread, gap and the positions;
- the last fills.

The server is a few lines of ``asyncio`` that answer GET requests on localhost only. It is a
viewer: nothing it serves feeds back into the run.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from importlib import resources
from pathlib import Path
from typing import Any

from marketimmune.paper.engine import Engine

HISTORY_MS = 10_000
MAX_POINTS = 720
TAPE = 40
LOG = 80
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ico": "image/x-icon",
}
CANDIDATES = ("improve+gap@0.25", "gap@0.25", "improve+gap@0.5", "gap@0.5")


class Board:
    def __init__(self) -> None:
        self.engine: Engine | None = None
        self.done: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.history: dict[str, list[tuple[int, float]]] = defaultdict(list)
        self.started_ms: int | None = None
        self.segments = 0
        self.gaps_done = 0
        self.next_sample = 0

    def attach(self, engine: Engine) -> None:
        self.engine = engine
        self.segments += 1
        self.started_ms = self.started_ms or int(time.time() * 1000)

    def close_segment(self, engine: Engine) -> None:
        """Fold a finished segment into the totals (each segment is marked to its last mid)."""
        for row in engine.summary()["instances"]:
            d = self.done[(row["coin"], row["strategy"])]
            for k in ("equity", "fills", "notional", "fees", "actions"):
                d[k] += row.get(k, 0)
        self.gaps_done += len(engine.gaps)
        self.engine = None

    def rows(self) -> list[dict[str, Any]]:
        """One row per coin and strategy: finished segments plus the running one."""
        cur = {(r["coin"], r["strategy"]): r for r in self.engine.summary()["instances"]} if self.engine else {}
        out = []
        for key in sorted(set(cur) | set(self.done)):
            r, d = cur.get(key, {}), self.done.get(key, {})
            out.append(
                {
                    "coin": key[0],
                    "strategy": key[1],
                    "pnl": d.get("equity", 0.0) + r.get("equity", 0.0),
                    "fills": int(d.get("fills", 0) + r.get("fills", 0)),
                    "notional": d.get("notional", 0.0) + r.get("notional", 0.0),
                    "actions": int(d.get("actions", 0) + r.get("actions", 0)),
                    "position_usd": r.get("position_usd", 0.0),
                }
            )
        return out

    def sample(self, now_ms: int) -> None:
        if now_ms < self.next_sample:
            return
        self.next_sample = now_ms + HISTORY_MS
        totals: dict[str, float] = defaultdict(float)
        for r in self.rows():
            totals[r["strategy"]] += r["pnl"]
        for strategy, pnl in totals.items():
            h = self.history[strategy]
            h.append((now_ms, round(pnl, 2)))
            if len(h) > 4 * MAX_POINTS:
                del h[::2]  # keep the whole run at a coarser step

    def state(self, now_ms: int) -> dict[str, Any]:
        rows = self.rows()
        hours = (now_ms - self.started_ms) / 3.6e6 if self.started_ms else 0.0
        strategies: dict[str, dict[str, Any]] = {}
        for r in rows:
            s = strategies.setdefault(
                r["strategy"], {"strategy": r["strategy"], "pnl": 0.0, "fills": 0, "notional": 0.0, "actions": 0, "gross_usd": 0.0}
            )
            s["pnl"] += r["pnl"]
            s["fills"] += r["fills"]
            s["notional"] += r["notional"]
            s["actions"] += r["actions"]
            s["gross_usd"] += abs(r["position_usd"])
        for s in strategies.values():
            s["bps"] = s["pnl"] / s["notional"] * 1e4 if s["notional"] else None
            s["per_hour"] = s["pnl"] / hours if hours > 0.01 else None
            s["actions_per_min"] = s["actions"] / (hours * 60) if hours > 0.01 else None
            s["candidate"] = s["strategy"] in CANDIDATES
        coins = []
        tape: list[dict[str, Any]] = []
        e = self.engine
        if e is not None:
            for c, st in e.states.items():
                top = st.top
                gap = st.gap()
                coins.append(
                    {
                        "coin": c,
                        "mid": top.mid if top else None,
                        "spread_bps": (top.ask - top.bid) / top.mid * 1e4 if top else None,
                        "gap_bps": gap,
                        "gap_z": gap / st.gap_sigma if gap is not None and st.gap_sigma else None,
                        "forecast_10s_bps": st.forecast(),
                        "model_1s_bps": st.predict(now_ms),
                        "sigma_1s_bps": st.sigma_1s,
                        "buy_burst": st.intensity_ratio(1, now_ms),
                        "sell_burst": st.intensity_ratio(-1, now_ms),
                        "positions": {r["strategy"]: r["position_usd"] for r in rows if r["coin"] == c},
                        "pnl": {r["strategy"]: r["pnl"] for r in rows if r["coin"] == c},
                    }
                )
            per: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for c, inst in e.instances():
                for t, side, px, qty, _ in inst.account.log[-TAPE:]:
                    per[inst.name].append({"t_ms": t, "coin": c, "strategy": inst.name, "side": side, "px": px, "usd": px * qty})
            for fills in per.values():  # the latest fills of every strategy, newest first
                tape += sorted(fills, key=lambda x: -x["t_ms"])[:TAPE]
            tape.sort(key=lambda x: -x["t_ms"])
            decisions, log = self.decisions(e, now_ms)
        else:
            decisions, log = [], []
        summary = e.summary() if e is not None else {}
        step = max(1, max((len(h) for h in self.history.values()), default=0) // MAX_POINTS)
        return {
            "now_ms": now_ms,
            "started_ms": self.started_ms,
            "hours": hours,
            "segment": self.segments,
            "last_event_ms": e.last_ms if e is not None else None,
            "feed_delay_ms": summary.get("feed_delay_ms_p10_p50_p90", {}),
            "reconnects": self.gaps_done + len(summary.get("connection_gaps", [])),
            "settings": summary.get("settings", {}) | {"fees_bps": summary.get("settings_fees_bps", {})},
            "strategies": sorted(strategies.values(), key=lambda s: -s["pnl"]),
            "coins": coins,
            "history": {k: h[::step] + h[-1:] for k, h in self.history.items()},
            "tape": tape,
            "decisions": decisions,
            "decision_log": log,
        }

    @staticmethod
    def decisions(e: Engine, now_ms: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Each maker's live quotes and the reason for them, per coin; and the latest changes of
        which sides each maker quotes, newest first."""
        rows: list[dict[str, Any]] = []
        log: list[dict[str, Any]] = []
        for c, makers in e.makers.items():
            st = e.states[c]
            for m in makers:
                quotes = {}
                for side, key in ((1, "bid"), (-1, "ask")):
                    o = m.current[side]
                    quotes[key] = None if o is None or o.qty <= 0 else {"px": o.px, "queue": o.queue, "live": o.t_live <= e.last_ms}
                top = st.top
                rows.append(
                    {
                        "coin": c,
                        "strategy": m.name,
                        **quotes,
                        "position_usd": m.account.position * top.mid if top else 0.0,
                        "reason": m.quoter.reason(st, now_ms),
                    }
                )
                log += [{"t_ms": t, "coin": c, "strategy": m.name, "sides": sides, "reason": why} for t, sides, why in m.events]
        log.sort(key=lambda x: -x["t_ms"])
        return rows, log[:LOG]

    async def serve(self, port: int, web: Path | None = None) -> asyncio.Server:
        """``/state.json`` (open to any origin, so the web terminal can read it from its own dev
        server), and either the built web terminal from ``web`` or the built-in page."""
        page = resources.files("marketimmune.paper").joinpath("dashboard.html").read_bytes()
        root = web.resolve() if web is not None else None

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                line = (await reader.readline()).decode(errors="replace").split()
                while (await reader.readline()) not in (b"\r\n", b"\n", b""):
                    pass
                path = line[1] if len(line) > 1 else "/"
                path = path.split("?", 1)[0]
                body, kind, code = b"not found", "text/plain", "404 Not Found"
                if path == "/state.json":
                    body, kind, code = json.dumps(self.state(int(time.time() * 1000))).encode(), "application/json", "200 OK"
                elif path == "/paper.html" or (root is None and path in ("/", "/index.html")):
                    body, kind, code = page, "text/html; charset=utf-8", "200 OK"
                elif root is not None:
                    target = (root / (path.lstrip("/") or "index.html")).resolve()
                    if target.is_relative_to(root) and target.is_file():
                        body, kind, code = target.read_bytes(), TYPES.get(target.suffix, "application/octet-stream"), "200 OK"
                head = (
                    f"HTTP/1.1 {code}\r\nContent-Type: {kind}\r\nContent-Length: {len(body)}\r\nCache-Control: no-store\r\n"
                    "Access-Control-Allow-Origin: *\r\nConnection: close\r\n\r\n"
                )
                writer.write(head.encode() + body)
                await writer.drain()
            finally:
                writer.close()

        return await asyncio.start_server(handle, "127.0.0.1", port)
