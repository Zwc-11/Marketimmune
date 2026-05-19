from __future__ import annotations

import math
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from dashboard.models import (
    DemoAgentEvent,
    DemoAgentTrace,
    DemoAlert,
    DemoFeatureRow,
    DemoMarketEvent,
    DemoPrediction,
    DemoTrainingRun,
)


@dataclass(frozen=True)
class DemoTick:
    market_event: DemoMarketEvent
    agent_event: DemoAgentEvent
    feature_row: DemoFeatureRow
    prediction: DemoPrediction
    alert: DemoAlert | None
    agent_trace: DemoAgentTrace


def _risk_label(score: float) -> str:
    if score >= 0.75:
        return 'critical'
    if score >= 0.55:
        return 'elevated'
    if score >= 0.35:
        return 'watch'
    return 'normal'


def create_demo_tick(symbol: str = 'BTCUSDT') -> DemoTick:
    """Create one complete simulated market, model, alert, and reasoning row."""

    sequence = DemoMarketEvent.objects.count() + 1
    timestamp = timezone.now()
    wave = math.sin(sequence / 3.0)
    pulse = 1 if sequence % 7 in {0, 1} else 0
    mid_price = 65000 + (wave * 85) + (sequence % 11) * 6
    spread_bps = 1.8 + (sequence % 5) * 0.25 + pulse * 1.4
    bid_price = mid_price * (1 - spread_bps / 20000)
    ask_price = mid_price * (1 + spread_bps / 20000)
    side = 'BUY' if sequence % 2 else 'SELL'
    quantity = round(0.018 + (sequence % 6) * 0.006 + pulse * 0.025, 4)
    order_price = ask_price if side == 'BUY' else bid_price
    cancel_rate = round(0.08 + (sequence % 4) * 0.09 + pulse * 0.26, 3)
    burst_rate = round(4.0 + (sequence % 9) * 1.7 + pulse * 9.0, 2)
    imbalance = round(abs(math.sin(sequence / 2.5)), 3)
    risk_score = min(0.98, round(0.18 + cancel_rate * 0.82 + burst_rate / 45 + pulse * 0.2, 3))
    label = _risk_label(risk_score)
    strategy = 'latency-burst-sweeper' if pulse else 'inventory-balancer'

    with transaction.atomic():
        market_event = DemoMarketEvent.objects.create(
            timestamp=timestamp,
            symbol=symbol,
            mid_price=round(mid_price, 2),
            bid_price=round(bid_price, 2),
            ask_price=round(ask_price, 2),
            spread_bps=round(spread_bps, 3),
        )
        agent_event = DemoAgentEvent.objects.create(
            market_event=market_event,
            agent_id='agent-alpha',
            strategy=strategy,
            simulated_order=f'{side} limit {quantity:.4f} {symbol} @ {order_price:.2f}',
            simulated_trade=f'filled {quantity * 0.72:.4f} {symbol} near {mid_price:.2f}',
            side=side,
            quantity=quantity,
            order_price=round(order_price, 2),
        )
        feature_row = DemoFeatureRow.objects.create(
            market_event=market_event,
            features={
                'cancel_rate_1s': cancel_rate,
                'order_burst_rate_1s': burst_rate,
                'spread_bps': round(spread_bps, 3),
                'side_imbalance': imbalance,
                'synthetic_agent_family': strategy,
            },
        )
        prediction = DemoPrediction.objects.create(
            feature_row=feature_row,
            model_name='Order-S2P2 risk head',
            risk_score=risk_score,
            risk_label=label,
            explanation=(
                'Burst rate and cancel pressure increased together.'
                if risk_score >= 0.55
                else 'Flow is within the normal simulated envelope.'
            ),
        )
        alert = None
        if risk_score >= 0.55:
            severity = 'high' if risk_score >= 0.75 else 'medium'
            alert = DemoAlert.objects.create(
                prediction=prediction,
                severity=severity,
                message=f'{severity.upper()} risk: {strategy} pattern on {symbol}',
            )
        agent_trace = DemoAgentTrace.objects.create(
            prediction=prediction,
            observation=f'{symbol} mid {mid_price:.2f}; spread {spread_bps:.2f} bps; {side} flow.',
            risk_evidence=[
                f'cancel_rate_1s={cancel_rate}',
                f'order_burst_rate_1s={burst_rate}',
                f'side_imbalance={imbalance}',
                f'risk_score={risk_score}',
            ],
            decision=f'classify as {label} risk',
            action='emit alert and slow agent' if risk_score >= 0.55 else 'continue monitoring',
            confidence=round(max(0.55, min(0.97, risk_score + 0.11)), 3),
        )

    return DemoTick(market_event, agent_event, feature_row, prediction, alert, agent_trace)


def seed_training_runs() -> None:
    runs = [
        {
            'model_name': 'RuleEngine baseline',
            'dataset_version': 'aegisbench-v0-phase7',
            'split_summary': '10800 train / 3630 validation / 3570 test',
            'pr_auc': 1.000,
            'f1': 0.655,
            'precision': 1.000,
            'recall': 0.487,
            'lead_time_ms': 128.7,
            'artifact_path': 'reports/phase7/benchmark_report.md',
        },
        {
            'model_name': 'GRU-MTPP',
            'dataset_version': 'aegisbench-v0-phase8',
            'split_summary': '360 train sequences / 119 eval sequences',
            'pr_auc': 0.999,
            'f1': 0.900,
            'precision': 0.940,
            'recall': 0.864,
            'lead_time_ms': 175.0,
            'artifact_path': 'reports/phase8/model_card.md',
        },
        {
            'model_name': 'Order-S2P2 risk head',
            'dataset_version': 'aegisbench-v0-phase9',
            'split_summary': 'synthetic scenarios with strict family split',
            'pr_auc': 0.941,
            'f1': 0.821,
            'precision': 0.872,
            'recall': 0.775,
            'lead_time_ms': 190.5,
            'artifact_path': 'reports/phase9/s2p2_model_card.md',
        },
    ]
    DemoTrainingRun.objects.all().delete()
    for run in runs:
        DemoTrainingRun.objects.create(**run)


def ensure_demo_seed(min_ticks: int = 8) -> None:
    seed_training_runs()
    while DemoMarketEvent.objects.count() < min_ticks:
        create_demo_tick()
