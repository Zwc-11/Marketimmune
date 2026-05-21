// Mirrors the JSON the Django service emits at /api/agentic/state/.
// Kept hand-written (not auto-generated from Pydantic) because the surface
// is small and we want explicit, recruiter-readable typings.

export interface AgentRunSummary {
    agent_name: string;
    goal: string;
    duration_ms: number;
    success: boolean;
    tool_call_count: number;
    trace_count: number;
}

export interface ScenarioProposal {
    name: string;
    base_scenario: string;
    cover_scenario: string | null;
    expected_attack: string;
    evasion_strategy: string;
    difficulty: string;
    rationale: string;
    rationale_source: 'llm' | 'deterministic' | null;
}

export interface InvestigationCase {
    case_id: string;
    suspected_behavior: string;
    severity: 'critical' | 'high' | 'medium' | 'low';
    confidence: number;
    matched_rules: string[];
    explanation: string;
    narrative: string;
    narrative_source: 'llm' | 'deterministic';
    feature_evidence: Record<string, number>;
    model_evidence: Record<string, unknown>;
    recommended_next_step: string;
}

export interface PolicyDecision {
    decision_id: string;
    case_id: string;
    recommended_action: string;
    severity: string;
    rationale: string;
    confidence: number;
}

export interface ImmuneMemory {
    memory_id: string;
    threat_name: string;
    description: string;
    key_signals: string[];
    best_detector: string;
    novelty_score: number;
    times_seen: number;
    last_seen_at: string;
}

export interface PromotionDecision {
    decision_id: string;
    verdict: 'promote' | 'reject' | 'needs_more_data';
    candidate_model: string;
    incumbent_model: string;
    rationale: string;
    metrics: {
        promote_votes?: number;
        reject_votes?: number;
        criteria?: Record<string, { passed: boolean; detail: string }>;
        candidate?: Record<string, unknown>;
        candidate_holdout?: Record<string, unknown>;
        incumbent?: Record<string, unknown>;
    };
    created_at: string;
}

export interface RecentLoop {
    loop_id: string;
    started_at: string;
    duration_ms: number;
    aggregate_posture: string;
    alert_count: number;
    case_count: number;
    new_memory_count: number;
    proposal_name: string;
}

export interface LoopState {
    loop: {
        loop_id: string;
        started_at: string;
        duration_ms: number;
        aggregate_posture: string;
        alert_count: number;
        case_count: number;
        new_memory_count: number;
        agent_runs: AgentRunSummary[];
        proposal: ScenarioProposal | null;
        cases: InvestigationCase[];
        decisions: PolicyDecision[];
    } | null;
    memories: ImmuneMemory[];
    promotion: PromotionDecision | null;
    recent_loops: RecentLoop[];
}

export interface LLMStatus {
    enabled: boolean;
    requested: boolean;
    has_key: boolean;
    provider: string;
    model: string;
}

export interface SimulatorScenario {
    name: string;
    label: string;
    family: string;
    description: string;
}

export interface SimulatorEvent {
    id: string;
    timestamp: string;
    price: number;
    open: number;
    high: number;
    low: number;
    close: number;
    quantity: number;
    bid: number | null;
    ask: number | null;
    mid_price: number | null;
    spread: number | null;
    volume: number;
    source: string;
    depth_levels: Array<{ percentage: number; depth: number; notional: number }>;
}

export interface SimulatorOrder {
    id: string;
    agent_id: string;
    strategy: string;
    timestamp: string;
    side: string;
    price: number;
    quantity: number;
    remaining_quantity: number;
    status: string;
}

export interface SimulatorPrediction {
    timestamp: string;
    model_name: string;
    risk_score: number;
    risk_label: string;
    explanation: string;
    confidence: number;
}

export interface SimulatorFeatureSnapshot {
    timestamp: string;
    features: Record<string, number>;
}

export interface SimulatorDecisionTrace {
    timestamp: string;
    observation: string;
    feature_evidence: Record<string, number>;
    model_interpretation: string;
    policy_decision: string;
    recommended_control: string;
    linked_event_id: string;
    linked_prediction_id: number;
}

export interface SimulatorCoverage {
    symbol: string;
    source: string;
    aligned_dates: string[];
    available_start: string | null;
    available_end: string | null;
    aligned_date_count: number;
    kline_date_count: number;
    depth_date_count: number;
    default_limit: number;
}

export interface SimulatorState {
    session_id: string;
    scenario_name: string;
    symbol: string;
    speed: number;
    status: string;
    event_count: number;
    session_start: string | null;
    session_end: string | null;
    session_date: string | null;
    market_coverage: SimulatorCoverage;
    scenarios: SimulatorScenario[];
    events: SimulatorEvent[];
    agent_orders: SimulatorOrder[];
    agent_trades: Array<{
        id: string;
        order_id: string;
        agent_id: string;
        timestamp: string;
        price: number;
        quantity: number;
        side: string;
    }>;
    feature_snapshots: SimulatorFeatureSnapshot[];
    predictions: SimulatorPrediction[];
    alerts: Array<{
        timestamp: string;
        severity: string;
        message: string;
        metric_name: string;
        metric_value: number;
    }>;
    decision_traces: SimulatorDecisionTrace[];
}
