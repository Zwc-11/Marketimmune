// JSON shapes served by the Django API in server/api (see server/api/views.py).

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

