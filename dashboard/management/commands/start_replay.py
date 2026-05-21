"""Build and persist a replay session.

This command is intentionally thin. All market-data loading, scenario
behaviour, and policy evaluation live in `marketimmune.simulator`; the
job of this module is just to:

  1. translate CLI arguments into a `ReplayConfig`,
  2. ask `ReplayBuilder` to build a deterministic `ReplayPlan`,
  3. write the plan to the Django ORM in a single transaction,
  4. emit human-readable progress.

That separation keeps the persistence concern out of the engine and the
engine concern out of Django.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from dashboard.models import (
    DecisionAuditTrace,
    FeatureSnapshot,
    ModelPrediction,
    ReplayCursor,
    ReplayEvent,
    ReplaySession,
    RiskAlert,
    SimulatedAgentOrder,
    SimulatedAgentTrade,
)
from marketimmune.simulator import (
    ReplayBuilder,
    ReplayConfig,
    ReplayPlan,
)

LAKE_ROOT = "data/lake/binance_usdm"
DEFAULT_MODEL_PATH = "data/models/risk_head.joblib"


class Command(BaseCommand):
    help = "Build and persist a deterministic BTC replay session."

    def add_arguments(self, parser):
        parser.add_argument("--symbol", default="BTCUSDT")
        parser.add_argument("--scenario", default="spoofing_layering")
        parser.add_argument("--speed", type=int, default=10)
        parser.add_argument("--limit", type=int, default=1440)
        parser.add_argument(
            "--date",
            default=None,
            help="UTC date YYYY-MM-DD to replay (defaults to first available).",
        )
        parser.add_argument(
            "--keep-old",
            action="store_true",
            help="Do not delete prior sessions before persisting this one.",
        )
        parser.add_argument(
            "--model-path",
            default=DEFAULT_MODEL_PATH,
            help=(
                "Path to a trained RiskScorer artifact. When the file "
                "exists the ML head is used; otherwise the rule engine "
                "score is shown. Use --no-ml-head to force rules."
            ),
        )
        parser.add_argument(
            "--no-ml-head",
            action="store_true",
            help="Force the rule-engine score even if a model exists.",
        )

    def handle(self, *args, **options):
        config = ReplayConfig(
            symbol=options["symbol"],
            scenario_name=options["scenario"],
            speed=options["speed"],
            limit=options["limit"],
            replay_date=options["date"],
        )
        self.stdout.write(self.style.SUCCESS(
            f"Building replay {config.scenario_name} "
            f"limit={config.limit} date={config.replay_date or 'auto'}"
        ))

        model_path = None if options["no_ml_head"] else options["model_path"]
        builder = ReplayBuilder.from_lake(LAKE_ROOT, model_path=model_path)
        if builder.risk_scorer is not None:
            self.stdout.write(self.style.SUCCESS(
                f"Loaded ML risk head: {builder.risk_scorer.MODEL_NAME}"
            ))
        else:
            self.stdout.write(self.style.WARNING(
                "ML risk head not available — using rule-engine score."
            ))
        try:
            plan = builder.build(config)
        except FileNotFoundError as exc:
            self.stdout.write(self.style.ERROR(str(exc)))
            return

        self.stdout.write(self.style.SUCCESS(
            f"Built {len(plan.ticks)} ticks "
            f"using {plan.depth_snapshot_count} depth snapshots."
        ))

        self._persist_plan(plan, keep_old=options["keep_old"])
        self.stdout.write(self.style.SUCCESS(
            f"Replay persisted run_id={plan.run_id}."
        ))

    # -- persistence ---------------------------------------------------

    @staticmethod
    @transaction.atomic
    def _persist_plan(plan: ReplayPlan, *, keep_old: bool) -> None:
        """Map a pure `ReplayPlan` onto the Django ORM in one transaction."""
        if not keep_old:
            ReplaySession.objects.all().delete()

        session = ReplaySession.objects.create(
            run_id=plan.run_id,
            symbol=plan.config.symbol,
            scenario_name=plan.config.scenario_name,
            speed=plan.config.speed,
            status="running",
        )
        ReplayCursor.objects.create(
            session=session,
            current_index=0,
            current_timestamp=timezone.now(),
            total_events=len(plan.ticks),
        )

        # Build all child rows in lists first, then bulk-create. This is
        # an order of magnitude faster than per-row .save() on SQLite.
        events: list[ReplayEvent] = []
        orders: list[SimulatedAgentOrder] = []
        trades: list[SimulatedAgentTrade] = []
        snapshots: list[FeatureSnapshot] = []
        predictions: list[ModelPrediction] = []
        alerts: list[RiskAlert] = []

        for t in plan.ticks:
            event_id = t.kline.event_id or f"ev-{plan.run_id}-{t.idx}"
            events.append(ReplayEvent(
                session=session,
                event_id=event_id,
                timestamp=t.timestamp,
                symbol=plan.config.symbol,
                event_type="kline",
                price=t.kline.close,
                quantity=t.kline.volume,
                bid=t.quote.bid,
                ask=t.quote.ask,
                mid_price=t.kline.close,
                spread=t.quote.spread,
                volume=t.kline.volume,
                source="binance_public",
                raw_payload=t.kline.raw,
                open_price=t.kline.open,
                high_price=t.kline.high,
                low_price=t.kline.low,
                depth_levels=t.depth.as_dicts() if t.depth else [],
            ))
            orders.append(SimulatedAgentOrder(
                session=session,
                event_id=f"order-{plan.run_id}-{t.idx}",
                order_id=f"ord-{plan.config.scenario_name}-{t.idx}",
                agent_id=f"agent-{plan.config.scenario_name}",
                strategy=plan.config.scenario_name,
                timestamp=t.timestamp,
                side=t.agent_side,
                price=t.agent_order_price,
                quantity=t.agent_order_quantity,
                remaining_quantity=max(
                    t.agent_order_quantity - t.agent_trade_quantity, 0.0
                ),
                status="filled" if t.agent_trade_quantity >= t.agent_order_quantity else "new",
            ))
            if t.agent_trade_quantity > 0:
                trades.append(SimulatedAgentTrade(
                    session=session,
                    trade_id=f"trade-{plan.run_id}-{t.idx}",
                    order_id=f"ord-{plan.config.scenario_name}-{t.idx}",
                    agent_id=f"agent-{plan.config.scenario_name}",
                    timestamp=t.timestamp,
                    price=t.agent_trade_price,
                    quantity=t.agent_trade_quantity,
                    side=t.agent_side,
                ))
            snapshots.append(FeatureSnapshot(
                session=session, timestamp=t.timestamp, features=t.features,
            ))
            predictions.append(ModelPrediction(
                session=session,
                timestamp=t.timestamp,
                model_name=t.risk_model_name,
                risk_score=t.risk_score,
                risk_label=t.risk_label,
                explanation=t.risk_explanation,
                confidence=0.92,
            ))
            if t.policy_decision != "allow":
                alerts.append(RiskAlert(
                    session=session,
                    timestamp=t.timestamp,
                    severity="CRITICAL" if t.policy_decision == "block" else "WARNING",
                    message=(
                        f"Potential {plan.config.scenario_name} detected. "
                        f"Score {t.risk_score:.2f}."
                    ),
                    metric_name="matched_rule_count",
                    metric_value=float(len(t.matched_rules)),
                ))

        ReplayEvent.objects.bulk_create(events)
        SimulatedAgentOrder.objects.bulk_create(orders)
        SimulatedAgentTrade.objects.bulk_create(trades)
        FeatureSnapshot.objects.bulk_create(snapshots)
        predictions = ModelPrediction.objects.bulk_create(predictions)
        RiskAlert.objects.bulk_create(alerts)

        # Audit traces reference the prediction PKs, so we create them
        # after the predictions exist.
        traces = []
        for t, pred in zip(plan.ticks, predictions, strict=False):
            traces.append(DecisionAuditTrace(
                session=session,
                timestamp=t.timestamp,
                observation=t.observation,
                feature_evidence=t.features,
                model_interpretation=t.risk_explanation,
                policy_decision=t.policy_decision,
                recommended_control=t.recommended_control,
                linked_event_id=t.kline.event_id or f"ev-{plan.run_id}-{t.idx}",
                linked_prediction_id=f"pred-{pred.id}",
            ))
        DecisionAuditTrace.objects.bulk_create(traces)

        session.status = "completed"
        session.save(update_fields=["status"])
