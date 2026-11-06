from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pytest

from marketimmune.paper.engine import Engine
from marketimmune.paper.events import RefTop, Top, Trade
from marketimmune.paper.journal import Journal, read

STRATEGIES = (
    "touch",
    "gap@0.25",
    "improve+gap@0.25",
    "model@0.5",
    "zgap@0.5",
    "hawkes@2",
    "kelly@0.5",
    "reservation@1",
    "taker@6",
)


def _run(journal: Journal | None, seconds: int = 1_500) -> Engine:
    """A random walk on SOL: Hyperliquid tops and trades every 70 ms, Coinbase leading by 300 ms."""
    rng = np.random.default_rng(7)
    e = Engine(("SOL",), latency_ms=200, strategies=STRATEGIES, sz_decimals={"SOL": 2}, budget_usd=3_000.0, journal=journal)
    true = 100.0
    path: list[float] = []
    t = 1_793_900_000_000
    for _ in range(seconds * 1000 // 70):
        t += 70
        true *= 1 + rng.normal(0, 2e-4)
        path.append(true)
        e.handle(RefTop("SOL", t, round(true - 0.005, 3), round(true + 0.005, 3)), t)
        seen = path[-5] if len(path) > 5 else true  # Hyperliquid lags 300 ms
        bid = float(np.floor(seen * 100 - 0.5) / 100)
        e.handle(Top("SOL", t, bid, float(rng.integers(1, 40)), round(bid + 0.01, 2), float(rng.integers(1, 40))), t + 400)
        if rng.random() < 0.6:
            buy = bool(rng.random() < 0.5 + 50 * (true - seen) / seen)
            px = round(bid + 0.01, 2) if buy else bid
            e.handle(Trade("SOL", t, px, float(rng.integers(1, 30)), buy, f"0x{rng.integers(0, 30)}"), t + 450)
        if t % 100 < 70:
            e.tick(t + 400)
    return e


def test_the_journal_does_not_change_a_run(tmp_path: Path) -> None:
    plain, kept = _run(None), _run(Journal(tmp_path / "journal"))
    assert len(plain.instances()) == len(kept.instances()) == len(STRATEGIES)
    for (_, a), (_, b) in zip(plain.instances(), kept.instances(), strict=True):
        assert a.account.log == b.account.log and a.actions == b.actions
    assert sum(len(i.account.log) for _, i in kept.instances()) > 100


def test_the_journal_lists_decisions_fills_and_counters(tmp_path: Path) -> None:
    e = _run(Journal(tmp_path / "journal"))
    e.write(tmp_path, final=True)
    j = tmp_path / "journal"
    fills = list(read(j / "fills.jsonl.gz"))
    assert len(fills) == sum(len(i.account.log) for _, i in e.instances())
    maker = [f for f in fills if f["kind"] == "maker"]
    assert maker and all(f["placed"] < f["live"] <= f["blk"] for f in maker)
    assert all(f["ctx"] is not None and f["mid0"] is not None for f in maker)
    assert {f["s"] for f in fills} >= {"touch", "gap@0.25"}
    decisions = list(read(j / "decisions.jsonl.gz"))
    by = {s: [d for d in decisions if d["s"] == s] for s in STRATEGIES if s != "taker@6"}
    assert all(by.values())  # every maker has at least its first side set
    for rows in by.values():
        assert all(a["sides"] != b["sides"] for a, b in zip(rows, rows[1:], strict=False))  # only changes
    minutes = list(read(j / "minutes.jsonl.gz"))
    touch = [m for m in minutes if m["s"] == "touch"]
    assert sum(m["fills"] for m in touch) == next(i for _, i in e.instances() if i.name == "touch").account.fills
    assert sum(m["orders"] + m["cancels"] for m in touch) == next(i for _, i in e.instances() if i.name == "touch").actions
    ms = sum(sum(m["ms"].values()) for m in touch)
    assert ms == pytest.approx(e.last_ms - by["touch"][0]["t"], abs=100)  # quoted or not, the whole run is covered
    signals = list(read(j / "signals.jsonl.gz"))
    assert len(signals) == pytest.approx(1_500, abs=5) and signals[-1]["gap"] is not None
    assert list(read(j / "taker.jsonl.gz"))  # the taker decided at least once


def test_a_journal_is_readable_while_written(tmp_path: Path) -> None:
    j = Journal(tmp_path)
    j.write("fills", {"a": 1})
    j.flush()
    j.write("fills", {"a": 2})  # not flushed: not yet readable
    assert [r["a"] for r in read(tmp_path / "fills.jsonl.gz")] == [1]
    j.close()
    j.close()  # twice is fine
    assert [r["a"] for r in read(tmp_path / "fills.jsonl.gz")] == [1, 2]
    with gzip.open(tmp_path / "fills.jsonl.gz", "rb") as fh:
        assert json.loads(fh.readline()) == {"a": 1}


def test_journal_report_reconciles_with_the_run(tmp_path: Path) -> None:
    from marketimmune.cli import paper_journal

    from .test_paper_engine import test_cli_replays_a_recording

    test_cli_replays_a_recording(tmp_path)
    run = tmp_path / "replayed"
    assert len(list(read(run / "journal" / "fills.jsonl.gz"))) == 7
    out = tmp_path / "journal.json"
    assert paper_journal.main(["--runs", str(run), "--out", str(out), "--md", str(tmp_path / "journal.md")]) == 0
    report = json.loads(out.read_text())["strategies"]
    summary = json.loads((run / "summary.json").read_text())
    for row in summary["instances"]:
        assert report[row["strategy"]]["pnl_usd"] == pytest.approx(row["equity"], abs=0.01)
    touch = report["touch"]
    assert touch["fills"] == 1 and touch["spread"] == pytest.approx(10 / 990 * 1e4, abs=0.01)  # bought at 99, mid 100 before
    assert touch["pnl_usd"] == pytest.approx(touch["spread_usd"] - touch["fee_usd"] + touch["inventory_usd"], abs=0.01)
    assert touch["splits"]["fill"][0]["bucket"] == "through"  # the trade at 98 went through the bid


def _recording(raw: Path, seconds: int = 400) -> list[tuple[int, str, bytes]]:
    """Messages as the live feeds deliver them, with the engine's ticks at uneven times (asyncio's)."""
    from marketimmune.paper.live import RawWriter

    rng = np.random.default_rng(3)
    w = RawWriter(raw)
    lines: list[tuple[int, str, bytes]] = []

    def put(venue: str, ns: int, msg: bytes) -> None:
        w.write(venue, ns, msg)
        lines.append((ns, venue, msg))

    t = 1_793_900_000_000
    true, seq, next_tick = 100.0, 0, t
    put(
        "cb",
        t * 1_000_000,
        json.dumps(
            {
                "channel": "l2_data",
                "sequence_num": seq,
                "events": [
                    {
                        "type": "snapshot",
                        "product_id": "SOL-USD",
                        "updates": [
                            {"side": "bid", "price_level": "99.995", "new_quantity": "5"},
                            {"side": "offer", "price_level": "100.005", "new_quantity": "5"},
                        ],
                    }
                ],
            }
        ).encode(),
    )
    path: list[float] = [true]
    for _ in range(seconds * 1000 // 70):
        t += 70
        old = round(true, 3)
        true *= 1 + rng.normal(0, 2e-4)
        path.append(true)
        new = round(true, 3)
        seq += 1
        put(
            "cb",
            (t + 30) * 1_000_000 + int(rng.integers(0, 999_999)),
            json.dumps(
                {
                    "channel": "l2_data",
                    "sequence_num": seq,
                    "events": [
                        {
                            "type": "update",
                            "product_id": "SOL-USD",
                            "updates": [
                                {"side": "bid", "price_level": f"{old - 0.005:.3f}", "new_quantity": "0"},
                                {"side": "offer", "price_level": f"{old + 0.005:.3f}", "new_quantity": "0"},
                                {"side": "bid", "price_level": f"{new - 0.005:.3f}", "new_quantity": "5"},
                                {"side": "offer", "price_level": f"{new + 0.005:.3f}", "new_quantity": "5"},
                            ],
                        }
                    ],
                }
            ).encode(),
        )
        seen = path[-5] if len(path) >= 5 else path[0]
        bid = float(np.floor(seen * 100 - 0.5) / 100)
        bbo = {
            "channel": "bbo",
            "data": {
                "coin": "SOL",
                "time": t,
                "bbo": [
                    {"px": f"{bid:.2f}", "sz": str(int(rng.integers(1, 40))), "n": 1},
                    {"px": f"{bid + 0.01:.2f}", "sz": str(int(rng.integers(1, 40))), "n": 1},
                ],
            },
        }
        put("hl", (t + 400) * 1_000_000 + int(rng.integers(0, 999_999)), json.dumps(bbo).encode())
        if rng.random() < 0.6:
            buy = bool(rng.random() < 0.5 + 50 * (true - seen) / seen)
            trade = {
                "channel": "trades",
                "data": [
                    {
                        "coin": "SOL",
                        "side": "B" if buy else "A",
                        "px": f"{bid + 0.01 if buy else bid:.2f}",
                        "sz": str(int(rng.integers(1, 30))),
                        "time": t,
                        "users": [f"0x{rng.integers(0, 30)}", "0xs"],
                    }
                ],
            }
            put("hl", (t + 450) * 1_000_000 + int(rng.integers(0, 999_999)), json.dumps(trade).encode())
        while next_tick + 100 <= t + 400:
            next_tick += 100 + int(rng.integers(0, 25))  # asyncio sleeps run late
            ns = next_tick * 1_000_000 + int(rng.integers(0, 999_999))
            put("tick", ns, b"%d" % (ns // 1_000_000))
    w.close()
    return sorted(lines)


def test_a_recording_with_its_ticks_replays_the_live_decisions(tmp_path: Path) -> None:
    from marketimmune.paper.events import CoinbaseBooks, parse_hl
    from marketimmune.paper.live import replay

    raw = tmp_path / "raw"
    lines = _recording(raw)

    def engine() -> Engine:
        return Engine(("SOL",), strategies=STRATEGIES, sz_decimals={"SOL": 2})

    live, books = engine(), CoinbaseBooks()  # what run_live does with the same messages
    for ns, venue, msg in lines:
        ms = ns // 1_000_000
        if venue == "tick":
            live.tick(int(msg))
        events = parse_hl(json.loads(msg), ms) if venue == "hl" else books.apply(json.loads(msg), ms) if venue == "cb" else []
        for ev in events:
            live.handle(ev, ms)
    replayed = engine()
    replay(replayed, raw)
    assert sum(len(i.account.log) for _, i in live.instances()) > 100
    for (_, a), (_, b) in zip(live.instances(), replayed.instances(), strict=True):
        assert a.account.log == b.account.log and a.actions == b.actions, a.name


def test_clock_offsets_come_from_coinbase_timestamps(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from marketimmune.paper.live import NETWORK_FLOOR_MS, RawWriter, clock_offsets, raw_lines, reclocked

    w = RawWriter(tmp_path)
    t0 = 1_793_981_206_000  # ms
    for i in range(240):  # four minutes, this clock 300 ms ahead and gaining 6 ms a minute (the PC gained 1)
        sent = t0 + i * 1_000
        ahead = 300 + 0.1 * i
        stamp = datetime.fromtimestamp(sent / 1e3, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "123Z"
        msg = json.dumps({"channel": "l2_data", "timestamp": stamp, "sequence_num": i, "events": []}, separators=(",", ":")).encode()
        w.write("cb", int((sent + NETWORK_FLOOR_MS + ahead) * 1e6), msg)
    w.close()
    offsets = clock_offsets(tmp_path)
    assert len(offsets) == 5  # the minutes touched
    assert min(offsets.values()) == pytest.approx(300, abs=1) and max(offsets.values()) < 300 + 24 + 1
    lines = list(raw_lines(tmp_path))
    fixed = list(reclocked(iter(lines), offsets))
    assert [x[0] for x in fixed] == sorted(x[0] for x in fixed)  # order kept
    lag = [(f[0] - o[0]) / 1e6 for f, o in zip(fixed, lines, strict=True)]
    assert -lag[0] == pytest.approx(300, abs=7) and -lag[-1] == pytest.approx(323.9, abs=7)
    assert [x[0] - 250_000_000 for x in lines] == [x[0] for x in reclocked(iter(lines), 250.0)]
