"""Service layer for the `/simulator/` cockpit.

Encapsulates two responsibilities:

1. **Ensure a session exists.** The cockpit always wants something to
   render; if no session has ever been built, we synchronously kick off
   one with safe defaults. After that, callers can rebuild on demand.

2. **Assemble the snapshot DTO** consumed by the React/JS front-end.
   We deliberately translate ORM rows into plain dicts here (not DRF
   serializers) because the cockpit needs a very specific shape and
   adding nested DRF serializers would be over-engineering for what is
   effectively one JSON document per page load.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.core.management import call_command

from dashboard.models import ReplaySession
from marketimmune.simulator import ReplayConfig, ScenarioRegistry
from marketimmune.simulator.data_loader import DepthRepository, KlineRepository

LAKE_ROOT = Path("data/lake/binance_usdm")


class SimulatorService:
    """Thin facade over the simulator persistence + DTO assembly."""

    DEFAULT_CONFIG = ReplayConfig(
        symbol="BTCUSDT",
        scenario_name="spoofing_layering",
        speed=10,
        limit=1440,
    )

    # -- session lifecycle -------------------------------------------

    def latest_session(self) -> ReplaySession | None:
        return ReplaySession.objects.order_by("-started_at").first()

    def ensure_session(self) -> ReplaySession:
        """Return the latest session, building a default one if missing."""
        session = self.latest_session()
        if session is not None:
            return session
        self.start(self.DEFAULT_CONFIG)
        session = self.latest_session()
        if session is None:  # pragma: no cover — only if start_replay failed silently
            raise RuntimeError("Simulator session could not be initialised.")
        return session

    def start(self, config: ReplayConfig) -> None:
        """Build and persist a new session synchronously."""
        call_command(
            "start_replay",
            symbol=config.symbol,
            scenario=config.scenario_name,
            speed=config.speed,
            limit=config.limit,
            date=config.replay_date,
        )

    # -- snapshot DTO -----------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Assemble the JSON payload consumed by the cockpit front-end."""
        session = self.ensure_session()

        events = session.events.all().order_by("timestamp")
        first_event = events.first()
        last_event = events.last()
        event_count = events.count()
        coverage = self.market_coverage(session.symbol)
        duration_ms = (
            (last_event.timestamp - first_event.timestamp).total_seconds() * 1000.0
            if first_event and last_event and last_event != first_event
            else 0.0
        )
        return {
            "session_id": session.run_id,
            "scenario_name": session.scenario_name,
            "symbol": session.symbol,
            "speed": session.speed,
            "status": session.status,
            "event_count": event_count,
            "session_start": first_event.timestamp.isoformat() if first_event else None,
            "session_end": last_event.timestamp.isoformat() if last_event else None,
            "session_date": first_event.timestamp.date().isoformat() if first_event else None,
            "duration_ms": duration_ms,
            "market_coverage": coverage,
            "scenarios": ScenarioRegistry.catalog(),
            "events": [
                {
                    "id": e.event_id,
                    "event_type": e.event_type,
                    "timestamp": e.timestamp.isoformat(),
                    "price": e.price,
                    "open": e.open_price,
                    "high": e.high_price,
                    "low": e.low_price,
                    "close": e.price,
                    "quantity": e.quantity,
                    "bid": e.bid,
                    "ask": e.ask,
                    "mid_price": e.mid_price,
                    "spread": e.spread,
                    "volume": e.volume,
                    "source": e.source,
                    "depth_levels": e.depth_levels,
                }
                for e in events
            ],
            "agent_orders": [
                {
                    "id": o.order_id,
                    "agent_id": o.agent_id,
                    "strategy": o.strategy,
                    "timestamp": o.timestamp.isoformat(),
                    "side": o.side,
                    "price": o.price,
                    "quantity": o.quantity,
                    "remaining_quantity": o.remaining_quantity,
                    "status": o.status,
                }
                for o in session.agent_orders.all().order_by("timestamp")
            ],
            "agent_trades": [
                {
                    "id": t.trade_id,
                    "order_id": t.order_id,
                    "agent_id": t.agent_id,
                    "timestamp": t.timestamp.isoformat(),
                    "price": t.price,
                    "quantity": t.quantity,
                    "side": t.side,
                    "notional": t.price * t.quantity,
                }
                for t in session.agent_trades.all().order_by("timestamp")
            ],
            "feature_snapshots": [
                {"timestamp": f.timestamp.isoformat(), "features": f.features}
                for f in session.feature_snapshots.all().order_by("timestamp")
            ],
            "predictions": [
                {
                    "timestamp": p.timestamp.isoformat(),
                    "model_name": p.model_name,
                    "risk_score": p.risk_score,
                    "risk_label": p.risk_label,
                    "explanation": p.explanation,
                    "confidence": p.confidence,
                }
                for p in session.predictions.all().order_by("timestamp")
            ],
            "alerts": [
                {
                    "id": a.id,
                    "timestamp": a.timestamp.isoformat(),
                    "severity": a.severity,
                    "message": a.message,
                    "metric_name": a.metric_name,
                    "metric_value": a.metric_value,
                }
                for a in session.alerts.all().order_by("timestamp")
            ],
            "decision_traces": [
                {
                    "timestamp": dt.timestamp.isoformat(),
                    "observation": dt.observation,
                    "feature_evidence": dt.feature_evidence,
                    "model_interpretation": dt.model_interpretation,
                    "policy_decision": dt.policy_decision,
                    "recommended_control": dt.recommended_control,
                    "linked_event_id": dt.linked_event_id,
                    "linked_prediction_id": dt.linked_prediction_id,
                }
                for dt in session.decision_traces.all().order_by("timestamp")
            ],
        }

    def market_coverage(self, symbol: str) -> dict[str, Any]:
        """Return local Binance lake coverage used by the simulator."""
        kline_repo = KlineRepository(LAKE_ROOT)
        depth_repo = DepthRepository(LAKE_ROOT)
        kline_dates = set(kline_repo.available_dates(symbol))
        depth_dates = set(depth_repo.available_dates(symbol))
        aligned_dates = sorted(kline_dates & depth_dates)
        return {
            "symbol": symbol,
            "source": "Binance Vision USD-M daily parquet lake",
            "aligned_dates": aligned_dates,
            "available_start": aligned_dates[0] if aligned_dates else None,
            "available_end": aligned_dates[-1] if aligned_dates else None,
            "aligned_date_count": len(aligned_dates),
            "kline_date_count": len(kline_dates),
            "depth_date_count": len(depth_dates),
            "default_limit": self.DEFAULT_CONFIG.limit,
        }
