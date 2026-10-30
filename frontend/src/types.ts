// Mirrors the JSON the Django service emits at /api/agentic/state/.
// Hand-written because the surface is small; keep in sync with dashboard/serializers.py
// and the service payloads under dashboard/services/.

export interface AgentRunSummary {
    run_id: string;
    agent_name: string;
    goal: string;
    started_at: string;
    finished_at: string;
    duration_ms: number;
    success: boolean;
    error: string;
    output: Record<string, unknown>;
    linked_artifacts: Record<string, unknown>;
    tool_call_count: number;
    trace_count: number;
    tool_calls: AgentToolCall[];
    decision_traces: AgentDecisionTrace[];
}

export interface AgentToolCall {
    tool: string;
    arguments: Record<string, unknown>;
    duration_ms: number;
    result_summary: string;
    occurred_at: string;
}

export interface AgentDecisionTrace {
    goal: string;
    observation: string;
    decision: string;
    confidence: number;
    evidence: Record<string, unknown>;
    occurred_at: string;
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
    alert_id: string;
    suspected_behavior: string;
    severity: 'critical' | 'high' | 'medium' | 'low';
    confidence: number;
    observation: string;
    timeline: Array<Record<string, unknown>>;
    matched_rules: string[];
    explanation: string;
    narrative: string;
    narrative_source: 'llm' | 'deterministic';
    feature_evidence: Record<string, number>;
    model_evidence: Record<string, unknown>;
    recommended_next_step: string;
    created_at: string;
}

export interface PolicyDecision {
    decision_id: string;
    case_id: string;
    recommended_action: string;
    severity: string;
    rationale: string;
    confidence: number;
    created_at: string;
}

export interface ImmuneMemory {
    memory_id: string;
    threat_name: string;
    description: string;
    scenario_source: string;
    key_signals: string[];
    best_detector: string;
    failed_detector: string;
    recommended_detector: string;
    example_case_id: string;
    novelty_score: number;
    times_seen: number;
    created_at: string;
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
        proposal_name: string;
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

export interface HyperliquidBackfillJob {
    job_id: string;
    status: 'running' | 'succeeded' | 'failed' | 'planned';
    trigger: string;
    coin: string;
    date: string;
    hours: number[];
    fill_suffixes: string[];
    lake_root: string;
    include_asset_ctxs: boolean;
    refresh_decisions: boolean;
    dry_run: boolean;
    book_snapshots: number;
    asset_contexts: number;
    fills: number;
    gold_rows: number;
    training_rows: number;
    writes: string[];
    refresh_run_id: number | null;
    message: string;
    started_at: string;
    finished_at: string | null;
    duration_ms: number;
}

export interface HyperliquidBackfillJobPayload {
    kind: 'hyperliquid_backfill_jobs';
    configured_limit: number;
    jobs: HyperliquidBackfillJob[];
}

export interface ArtifactStatus {
    label: string;
    path: string;
    exists: boolean;
}

export interface MarkoutMetricBlock {
    n_rows?: number;
    training_rows?: number;
    pr_auc?: number;
    brier?: number;
    ece?: number;
    markout_lift_bps?: number;
    quote_rate?: number;
    latency_p95_ms?: number;
    leakage_safe?: boolean;
    coins?: string[];
    dates?: string[];
    partition_rows?: Array<Record<string, unknown>>;
}

export interface MarkoutModelHealth {
    available: boolean;
    kind: 'hyperliquid_markout';
    message?: string;
    model_name?: string;
    instrument?: string;
    horizon?: string;
    dataset_label?: string;
    cv_scheme?: string;
    decision_threshold?: number | null;
    feature_count?: number;
    feature_columns?: string[];
    artifacts?: {
        model: ArtifactStatus;
        calibrator: ArtifactStatus;
        report: ArtifactStatus;
    };
    missing_artifacts?: ArtifactStatus[];
    training?: MarkoutMetricBlock;
    holdout?: MarkoutMetricBlock | null;
    baseline_comparison?: Record<string, Record<string, number>>;
    holdout_baseline_comparison?: Record<string, Record<string, number>>;
    smoke_prediction?: {
        raw_score: number;
        calibrated_score: number;
        decision_threshold: number | null;
        action: string;
    };
    smoke_latency?: {
        p50_ms: number;
        p95_ms: number;
        p99_ms: number;
        mean_ms: number;
    };
}

export interface MarkoutFillDecision {
    decision_id: string;
    coin: string;
    ts_ms: number;
    timestamp: string;
    px: number;
    sz: number;
    side: string;
    maker_side: number;
    model_name: string;
    raw_score: number;
    calibrated_score: number;
    decision_threshold: number | null;
    action: string;
    severity: 'critical' | 'high' | 'medium' | 'low';
    markout_bps: number | null;
    toxic: boolean | null;
    tid: number | null;
    oid: number | null;
    top_features: string[];
    feature_values: Record<string, number>;
    source_path: string;
    loop_id: string;
    case_id: string;
    policy_decision_id: string;
    recommended_action: string;
    scored_at: string;
}

export interface MarkoutDecisionRefresh {
    id: number;
    status: 'running' | 'succeeded' | 'failed' | 'skipped';
    trigger: string;
    source_path: string;
    requested_limit: number;
    refreshed_count: number;
    message: string;
    started_at: string;
    finished_at: string | null;
    duration_ms: number;
}

export interface MarkoutFillDecisionPayload {
    available: boolean;
    kind: 'hyperliquid_markout_fill_decisions';
    source_path: string;
    configured_limit: number;
    refresh_attempted: boolean;
    refreshed_count: number;
    message: string;
    latest_refresh: MarkoutDecisionRefresh | null;
    decisions: MarkoutFillDecision[];
}

