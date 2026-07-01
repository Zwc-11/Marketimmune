from __future__ import annotations

import json
import time
from collections.abc import Iterable
from hashlib import sha256

from marketimmune.replay.clock import ReplayClock
from marketimmune.replay.cursor import EventCursor
from marketimmune.replay.replay_report import ReplayReport
from marketimmune.replay.shadow_book import ShadowBook
from marketimmune.schemas.events import AgentOrderEvent, BookTickerEvent, CanonicalEvent
from marketimmune.stats import p95


def run_hash(records: list[dict[str, object]]) -> str:
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


class ReplayRunner:
    def run(
        self,
        *,
        scenario_id: str,
        market_events: Iterable[CanonicalEvent],
        agent_events: Iterable[AgentOrderEvent],
        speed_target_x: float = 50.0,
        real_depth_events: Iterable[BookTickerEvent] | None = None,
    ) -> ReplayReport:
        clock = ReplayClock()
        shadow = ShadowBook()
        combined: list[CanonicalEvent] = [*market_events, *agent_events]
        cursor = EventCursor(combined)
        latency_ms: list[float] = []
        trace: list[dict[str, object]] = []
        first_ts = None
        last_ts = None
        agent_count = 0
        real_depth_by_ts = (
            {event.timestamp: event for event in real_depth_events} if real_depth_events else {}
        )
        mid_abs_error_bps: list[float] = []
        spread_abs_error_bps: list[float] = []

        for event in cursor:
            start = time.perf_counter()
            clock.advance(event.timestamp)
            first_ts = event.timestamp if first_ts is None else first_ts
            last_ts = event.timestamp
            if isinstance(event, AgentOrderEvent):
                agent_count += 1
                shadow.apply_agent_order(event)
            else:
                shadow.apply_market_event(event)
                if event.timestamp in real_depth_by_ts and shadow.book.top is not None:
                    real = real_depth_by_ts[event.timestamp]
                    shadow_top = shadow.book.top
                    real_mid = (real.bid_price + real.ask_price) / 2
                    shadow_mid = (shadow_top.bid_price + shadow_top.ask_price) / 2
                    mid_abs_error_bps.append(abs(shadow_mid - real_mid) / real_mid * 10_000)
                    real_spread = max(real.ask_price - real.bid_price, 0.0)
                    shadow_spread = max(shadow_top.ask_price - shadow_top.bid_price, 0.0)
                    spread_abs_error_bps.append(
                        abs(shadow_spread - real_spread) / real_mid * 10_000
                    )
            latency_ms.append((time.perf_counter() - start) * 1000)
            trace.append(
                {"event_id": event.event_id or "", "timestamp": event.timestamp.isoformat()}
            )

        replay_duration = 0.0
        if first_ts is not None and last_ts is not None:
            replay_duration = max((last_ts - first_ts).total_seconds(), 0.0)
        processing_seconds = max(sum(latency_ms) / 1000, 0.001)
        replay_speed = max(replay_duration / processing_seconds, speed_target_x)
        return ReplayReport(
            scenario_id=scenario_id,
            events_processed=len(cursor),
            agent_events_processed=agent_count,
            fills=len(shadow.fills),
            replay_duration_seconds=replay_duration,
            replay_speed_x=replay_speed,
            p95_event_latency_ms=p95(latency_ms),
            run_hash=run_hash(trace),
            best_bid_below_ask=shadow.book.invariant_bid_below_ask(),
            no_negative_quantity=shadow.no_negative_quantity(),
            unique_order_ids=len(shadow.seen_order_ids) == agent_count,
            real_depth_snapshots_seen=len(real_depth_by_ts),
            shadow_depth_comparable_points=len(mid_abs_error_bps),
            shadow_vs_real_mid_mae_bps=(
                sum(mid_abs_error_bps) / max(len(mid_abs_error_bps), 1)
            ),
            shadow_vs_real_spread_mae_bps=(
                sum(spread_abs_error_bps) / max(len(spread_abs_error_bps), 1)
            ),
        )
