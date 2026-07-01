// Deterministic live-stream engine for the static SPA.
//
// Ported from the old Django `dashboard/demo_data.py` math, but rebased onto the
// v2 vocabulary (CLAUDE.md §0): Hyperliquid `BTC-PERP` perp microstructure and a
// realized-markout *toxicity* score, not Binance spot risk. The engine is a pure,
// seeded generator so every reload produces the same stream — the DataProvider
// just calls `tick()` on an interval to make charts/tickers/3D feel live.
//
// IMPORTANT: this is a SYNTHETIC preview generator. Every value below (prices,
// toxicity, markout bps, model name) is illustrative — NOT a live feed and NOT the
// output of a trained model. It previews the target (v2) system; see
// AUDIT_AND_PLAN.md. The UI carries a persistent "Preview · simulated data" badge.

import type {
    SimulatorAlert,
    SimulatorCoverage,
    SimulatorDecisionTrace,
    SimulatorEvent,
    SimulatorFeatureSnapshot,
    SimulatorOrder,
    SimulatorPrediction,
    SimulatorScenario,
    SimulatorState,
    SimulatorTrade,
} from '../types';

const SYMBOL = 'BTC-PERP';
const MID_ANCHOR = 65_000; // BTC-PERP mid anchor, in USD
const SESSION_START_MS = Date.parse('2025-10-10T13:00:00Z'); // replayed historical window
const BAR_INTERVAL_MS = 60_000; // one 1m kline per tick
const MAX_BUFFER = 240; // keep the trailing window bounded

// Episodes named after real historical events; the data here is a deterministic
// SYNTHETIC preview, not a replay of real fills.
export const SCENARIOS: SimulatorScenario[] = [
    {
        name: 'oct_2025_cascade',
        label: 'Oct-2025 liquidation cascade',
        family: 'liquidation_cascade',
        description: 'Self-reinforcing long liquidations driving sharp adverse selection on resting bids.',
    },
    {
        name: 'jelly_playbook',
        label: 'JELLY squeeze playbook',
        family: 'oracle_squeeze',
        description: 'Oracle/perp basis dislocation used to pick off makers around the HLP vault.',
    },
    {
        name: 'funding_flip',
        label: 'Funding rate-of-change flip',
        family: 'funding_shock',
        description: 'Rapid funding sign flip with one-sided order-flow imbalance and widening spread.',
    },
    {
        name: 'calm_baseline',
        label: 'Calm baseline session',
        family: 'baseline',
        description: 'Low-toxicity control window used as the always-quote lift baseline.',
    },
];

export const MARKET_COVERAGE: SimulatorCoverage = {
    symbol: SYMBOL,
    source: 'Simulated (preview)',
    aligned_dates: ['2025-10-08', '2025-10-09', '2025-10-10'],
    available_start: '2025-10-08',
    available_end: '2025-10-10',
    aligned_date_count: 3,
    kline_date_count: 3,
    depth_date_count: 3,
    default_limit: 120,
};

/** Small, fast seeded PRNG (mulberry32) so the stream is reproducible. */
function mulberry32(seed: number): () => number {
    let state = seed >>> 0;
    return () => {
        state |= 0;
        state = (state + 0x6d2b79f5) | 0;
        let t = Math.imul(state ^ (state >>> 15), 1 | state);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

function toxicityLabel(score: number): string {
    if (score >= 0.75) return 'critical';
    if (score >= 0.55) return 'elevated';
    if (score >= 0.35) return 'watch';
    return 'normal';
}

function isoAt(sequence: number): string {
    return new Date(SESSION_START_MS + sequence * BAR_INTERVAL_MS).toISOString();
}

/** One fully-derived simulated bar: the same `wave/pulse` shape as demo_data.py. */
interface Tick {
    event: SimulatorEvent;
    prediction: SimulatorPrediction;
    feature: SimulatorFeatureSnapshot;
    trace: SimulatorDecisionTrace;
    alert: SimulatorAlert | null;
    order: SimulatorOrder | null;
    trade: SimulatorTrade | null;
}

function buildTick(sequence: number, rng: () => number): Tick {
    const timestamp = isoAt(sequence);
    const wave = Math.sin(sequence / 3);
    const pulse = sequence % 7 <= 1 ? 1 : 0;

    const mid = MID_ANCHOR + wave * 85 + (sequence % 11) * 6;
    const spreadBps = 1.8 + (sequence % 5) * 0.25 + pulse * 1.4;
    const bid = mid * (1 - spreadBps / 20_000);
    const ask = mid * (1 + spreadBps / 20_000);
    const open = mid - wave * 22;
    const high = Math.max(open, mid) + 18 + pulse * 30;
    const low = Math.min(open, mid) - 18 - pulse * 30;
    const side = sequence % 2 ? 'BUY' : 'SELL';
    const quantity = Number((0.018 + (sequence % 6) * 0.006 + pulse * 0.025).toFixed(4));
    const orderPrice = side === 'BUY' ? ask : bid;
    const volume = Number((1.4 + (sequence % 8) * 0.4 + pulse * 2.1).toFixed(2));

    // v2 microstructure signals (CLAUDE.md §0): OFI, microprice basis, funding RoC, OI delta.
    const orderFlowImbalance = Number(Math.abs(Math.sin(sequence / 2.5)).toFixed(3));
    const cancelRate = Number((0.08 + (sequence % 4) * 0.09 + pulse * 0.26).toFixed(3));
    const burstRate = Number((4 + (sequence % 9) * 1.7 + pulse * 9).toFixed(2));
    const fundingRoc = Number(((wave + rng() * 0.4 - 0.2) * 0.6).toFixed(3));
    const oiDelta = Number(((sequence % 5) - 2 + rng()).toFixed(2));

    const toxicity = Math.min(
        0.98,
        Number((0.18 + cancelRate * 0.82 + burstRate / 45 + pulse * 0.2).toFixed(3)),
    );
    // Realized 10s markout (bps): negative when the maker is picked off.
    const markoutBps = Number(((0.5 - toxicity) * 9.5).toFixed(2));
    const label = toxicityLabel(toxicity);
    const strategy = pulse ? 'latency-burst-sweeper' : 'inventory-balancer';

    const event: SimulatorEvent = {
        id: `evt-${sequence}`,
        event_type: 'kline',
        timestamp,
        symbol: SYMBOL,
        price: Number(mid.toFixed(2)),
        open: Number(open.toFixed(2)),
        high: Number(high.toFixed(2)),
        low: Number(low.toFixed(2)),
        close: Number(mid.toFixed(2)),
        quantity,
        bid: Number(bid.toFixed(2)),
        ask: Number(ask.toFixed(2)),
        mid_price: Number(mid.toFixed(2)),
        spread: Number((ask - bid).toFixed(2)),
        volume,
        source: 'Simulated (preview)',
        depth_levels: [0.1, 0.25, 0.5, 1].map((percentage) => ({
            percentage,
            depth: Number((volume * (1.6 - percentage)).toFixed(2)),
            notional: Number((volume * mid * (1.6 - percentage)).toFixed(0)),
        })),
    };

    const prediction: SimulatorPrediction = {
        timestamp,
        model_name: 'CatBoost markout classifier',
        risk_score: toxicity,
        risk_label: label,
        explanation:
            toxicity >= 0.55
                ? 'Order-flow imbalance and cancel pressure rose together; markout turning negative.'
                : 'Flow is within the calm-quoting envelope; markout near zero.',
        confidence: Number(Math.max(0.55, Math.min(0.97, toxicity + 0.11)).toFixed(3)),
    };

    const feature: SimulatorFeatureSnapshot = {
        timestamp,
        features: {
            order_flow_imbalance: orderFlowImbalance,
            cancel_rate_1s: cancelRate,
            order_burst_rate_1s: burstRate,
            spread_bps: Number(spreadBps.toFixed(3)),
            funding_rate_of_change: fundingRoc,
            open_interest_delta: oiDelta,
            realized_markout_bps: markoutBps,
        },
    };

    const trace: SimulatorDecisionTrace = {
        timestamp,
        observation: `${SYMBOL} mid ${mid.toFixed(2)}; spread ${spreadBps.toFixed(2)} bps; ${side} flow.`,
        feature_evidence: {
            order_flow_imbalance: orderFlowImbalance,
            cancel_rate_1s: cancelRate,
            realized_markout_bps: markoutBps,
            toxicity_score: toxicity,
        },
        model_interpretation: `Classified as ${label} toxicity (markout ${markoutBps} bps).`,
        policy_decision: toxicity >= 0.55 ? 'widen_quotes' : 'continue_quoting',
        recommended_control:
            toxicity >= 0.75 ? 'pull resting quotes' : toxicity >= 0.55 ? 'widen spread' : 'hold',
        linked_event_id: event.id,
        linked_prediction_id: sequence,
    };

    const alert: SimulatorAlert | null =
        toxicity >= 0.55
            ? {
                  id: sequence,
                  timestamp,
                  severity: toxicity >= 0.75 ? 'critical' : 'medium',
                  message: `${toxicity >= 0.75 ? 'CRITICAL' : 'ELEVATED'} toxicity: ${strategy} on ${SYMBOL}`,
                  metric_name: 'realized_markout_bps',
                  metric_value: markoutBps,
              }
            : null;

    const order: SimulatorOrder | null = pulse
        ? {
              id: `ord-${sequence}`,
              agent_id: 'agent-alpha',
              strategy,
              timestamp,
              side,
              price: Number(orderPrice.toFixed(2)),
              quantity,
              remaining_quantity: Number((quantity * 0.28).toFixed(4)),
              status: 'partially_filled',
          }
        : null;

    const trade: SimulatorTrade | null = pulse
        ? {
              id: `trd-${sequence}`,
              order_id: `ord-${sequence}`,
              agent_id: 'agent-alpha',
              timestamp,
              price: Number(mid.toFixed(2)),
              quantity: Number((quantity * 0.72).toFixed(4)),
              side,
              notional: Number((mid * quantity * 0.72).toFixed(2)),
              pnl: Number((markoutBps * quantity).toFixed(2)),
          }
        : null;

    return { event, prediction, feature, trace, alert, order, trade };
}

export interface SimEngine {
    /** Current immutable snapshot of the replay state. */
    snapshot(): SimulatorState;
    /** Append one new simulated bar (bounded buffer). */
    tick(): void;
    /** Latest toxicity score in [0, 1] — drives the Three.js hero. */
    risk(): number;
    /** Rebuild the stream for a different historical scenario. */
    setScenario(name: string): void;
}

export function createSimEngine(scenarioName: string = SCENARIOS[0].name): SimEngine {
    let scenario = SCENARIOS.find((s) => s.name === scenarioName) ?? SCENARIOS[0];
    let rng = mulberry32(hashScenario(scenario.name));
    let sequence = 0;

    const events: SimulatorEvent[] = [];
    const predictions: SimulatorPrediction[] = [];
    const featureSnapshots: SimulatorFeatureSnapshot[] = [];
    const decisionTraces: SimulatorDecisionTrace[] = [];
    const alerts: SimulatorAlert[] = [];
    const orders: SimulatorOrder[] = [];
    const trades: SimulatorTrade[] = [];

    function pushBounded<T>(list: T[], value: T): void {
        list.push(value);
        if (list.length > MAX_BUFFER) list.shift();
    }

    function advance(): void {
        const tick = buildTick(sequence, rng);
        pushBounded(events, tick.event);
        pushBounded(predictions, tick.prediction);
        pushBounded(featureSnapshots, tick.feature);
        pushBounded(decisionTraces, tick.trace);
        if (tick.alert) pushBounded(alerts, tick.alert);
        if (tick.order) pushBounded(orders, tick.order);
        if (tick.trade) pushBounded(trades, tick.trade);
        sequence += 1;
    }

    function reset(name: string): void {
        scenario = SCENARIOS.find((s) => s.name === name) ?? SCENARIOS[0];
        rng = mulberry32(hashScenario(scenario.name));
        sequence = 0;
        [events, predictions, featureSnapshots, decisionTraces, alerts, orders, trades].forEach(
            (list) => (list.length = 0),
        );
        for (let i = 0; i < 90; i += 1) advance(); // warm start so charts open populated
    }

    reset(scenario.name);

    return {
        tick: advance,
        risk: () => predictions[predictions.length - 1]?.risk_score ?? 0,
        setScenario: reset,
        snapshot: (): SimulatorState => ({
            session_id: `sim-${scenario.name}`,
            scenario_name: scenario.name,
            symbol: SYMBOL,
            speed: 1,
            status: 'running',
            event_count: sequence,
            session_start: events[0]?.timestamp ?? null,
            session_end: events[events.length - 1]?.timestamp ?? null,
            session_date: MARKET_COVERAGE.available_end,
            duration_ms: sequence * BAR_INTERVAL_MS,
            market_coverage: MARKET_COVERAGE,
            scenarios: SCENARIOS,
            events: [...events],
            agent_orders: [...orders],
            agent_trades: [...trades],
            feature_snapshots: [...featureSnapshots],
            predictions: [...predictions],
            alerts: [...alerts],
            decision_traces: [...decisionTraces],
        }),
    };
}

function hashScenario(name: string): number {
    let hash = 2166136261;
    for (let i = 0; i < name.length; i += 1) {
        hash ^= name.charCodeAt(i);
        hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
}
