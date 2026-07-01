// Static fixtures for the SPA's persisted entities (CLAUDE.md §0).
//
// IMPORTANT: these are ILLUSTRATIVE PREVIEW fixtures, not outputs of a trained
// model or a live data feed. They depict the TARGET (v2) system so the UI can be
// reviewed before the backend exists. The model names (e.g. "CatBoost markout
// classifier") and metrics here describe what we are building toward, not what is
// implemented today — see AUDIT_AND_PLAN.md. The UI shows a persistent
// "Preview · simulated data" badge to make this unambiguous.
//
// These mirror the shapes the Django serializers emit (see frontend/src/types.ts)
// so the app renders fully with NO backend. Numbers are kept on the honest v2
// range (PR-AUC ~0.76–0.84, realized markout lift in bps), never the v1 0.99 story.

import type {
    AgentRunSummary,
    BenchmarkMetric,
    ImmuneMemory,
    InvestigationCase,
    LLMStatus,
    LoopState,
    ModelMetric,
    PolicyDecision,
    PromotionDecision,
    RecentLoop,
    ScenarioProposal,
    TrainingRun,
} from '../types';

const LOOP_ID = 'loop-2025-10-10-13';
const LOOP_START = '2025-10-10T13:04:21Z';

export const SEED_LLM: LLMStatus = {
    enabled: false,
    requested: false,
    has_key: false,
    provider: 'deepseek',
    model: 'deepseek-v4-pro',
};

const PROPOSAL: ScenarioProposal = {
    name: 'replay-oct-2025-cascade',
    base_scenario: 'oct_2025_cascade',
    cover_scenario: 'funding_flip',
    expected_attack: 'liquidation-driven adverse selection on resting bids',
    evasion_strategy: 'stagger maker quotes behind a benign funding-arb cover to delay detection',
    difficulty: 'hard',
    rationale:
        'Replays the Oct-2025 cascade: one-sided OFI plus a funding sign-flip picks off makers before spreads widen.',
    rationale_source: 'deterministic',
};

function toolCall(tool: string, summary: string, ms: number, args: Record<string, unknown> = {}) {
    return {
        tool,
        arguments: args,
        duration_ms: ms,
        result_summary: summary,
        occurred_at: LOOP_START,
    };
}

function decisionTrace(goal: string, observation: string, decision: string, confidence: number) {
    return { goal, observation, decision, confidence, evidence: {}, occurred_at: LOOP_START };
}

function agentRun(
    name: string,
    goal: string,
    durationMs: number,
    extras: Partial<AgentRunSummary> = {},
): AgentRunSummary {
    return {
        run_id: `${LOOP_ID}-${name.toLowerCase()}`,
        agent_name: name,
        goal,
        started_at: LOOP_START,
        finished_at: LOOP_START,
        duration_ms: durationMs,
        success: true,
        error: '',
        output: {},
        linked_artifacts: {},
        tool_call_count: extras.tool_calls?.length ?? 0,
        trace_count: extras.decision_traces?.length ?? 0,
        tool_calls: [],
        decision_traces: [],
        ...extras,
    };
}

export const SEED_AGENT_RUNS: AgentRunSummary[] = [
    agentRun('RedTeam', 'Propose a historical toxic episode to replay', 412, {
        tool_calls: [toolCall('select_episode', 'Selected Oct-2025 cascade as base episode', 120)],
        decision_traces: [
            decisionTrace(
                'choose replay',
                'Cascade window has dense maker pick-offs',
                'replay oct_2025_cascade under funding-flip cover',
                0.82,
            ),
        ],
    }),
    agentRun('Simulator', 'Replay BTC-PERP microstructure for the episode', 988, {
        tool_calls: [toolCall('build_replay', 'Rebuilt 120 BTC-PERP bars from S3 archive', 740)],
    }),
    agentRun('Sentinel', 'Score maker fills for adverse selection', 156, {
        tool_calls: [toolCall('score_fills', 'Flagged 6 fills with toxicity > 0.55', 96)],
        decision_traces: [
            decisionTrace('detect', '6 fills crossed toxicity threshold', 'open investigation case', 0.91),
        ],
    }),
    agentRun('Investigator', 'Build evidence and narrative for the worst fill', 1340, {
        tool_calls: [
            toolCall('trace_counterparty', 'Linked aggressor to liquidation-cascade flow', 210),
            toolCall('cross_reference', 'Concurrent funding sign-flip confirmed', 180),
        ],
        decision_traces: [
            decisionTrace('investigate', 'Markout -6.4 bps with one-sided OFI', 'classify critical toxicity', 0.88),
        ],
    }),
    agentRun('Policy', 'Decide a quoting control', 88, {
        tool_calls: [toolCall('emit_command', 'Issued widen-and-pull command', 40)],
        decision_traces: [decisionTrace('decide', 'Critical toxicity sustained', 'pull resting quotes', 0.9)],
    }),
    agentRun('Memory', 'Persist the episode to immune memory', 73, {
        tool_calls: [toolCall('upsert_memory', 'Reinforced "Oct-2025 cascade pick-off" memory', 36)],
    }),
    agentRun('Trainer', 'Refit the markout challenger on the episode', 2210, {
        tool_calls: [toolCall('fit_challenger', 'Challenger PR-AUC 0.81 under purged CV', 2010)],
    }),
    agentRun('Judge', 'Evaluate challenger vs champion', 134, {
        tool_calls: [toolCall('score_promotion', 'Challenger met 3/5 promotion criteria', 80)],
        decision_traces: [decisionTrace('judge', 'Markout lift +0.4 bps, calibration improved', 'needs more data', 0.7)],
    }),
];

export const SEED_CASES: InvestigationCase[] = [
    {
        case_id: 'case-001',
        alert_id: 'alert-42',
        suspected_behavior: 'Liquidation-cascade pick-off of resting bids',
        severity: 'critical',
        confidence: 0.88,
        observation: 'BTC-PERP maker bid filled 40ms before a 6.4 bps adverse move during a long-liquidation burst.',
        timeline: [
            { t: '13:04:18Z', event: 'Funding rate-of-change flips negative' },
            { t: '13:04:21Z', event: 'One-sided sell OFI spikes to 0.94' },
            { t: '13:04:21Z', event: 'Maker bid filled, then mid drops 6.4 bps in 10s' },
        ],
        matched_rules: ['one_sided_ofi', 'funding_sign_flip', 'negative_markout_10s'],
        explanation: 'OFI imbalance + funding flip preceded a negative realized markout — classic adverse selection.',
        narrative:
            'During the Oct-2025 cascade replay, a resting BTC-PERP bid was picked off as cascading long liquidations '
            + 'pushed one-sided sell flow. Realized 10s markout was -6.4 bps. The signature matches the cascade memory.',
        narrative_source: 'deterministic',
        feature_evidence: {
            order_flow_imbalance: 0.94,
            funding_rate_of_change: -0.41,
            realized_markout_bps: -6.4,
            toxicity_score: 0.86,
        },
        model_evidence: { model_name: 'CatBoost markout classifier', risk_score: 0.86 },
        recommended_next_step: 'Pull resting quotes for 30s and widen on the liquidation side.',
        created_at: LOOP_START,
    },
    {
        case_id: 'case-002',
        alert_id: 'alert-43',
        suspected_behavior: 'Oracle/perp basis squeeze (JELLY-style)',
        severity: 'high',
        confidence: 0.74,
        observation: 'Microprice diverged from oracle mid while spread widened ahead of a basis snap-back.',
        timeline: [
            { t: '13:06:02Z', event: 'Perp-oracle basis widens beyond 8 bps' },
            { t: '13:06:05Z', event: 'Maker ask filled into the dislocation' },
        ],
        matched_rules: ['perp_oracle_basis', 'microprice_divergence'],
        explanation: 'Basis dislocation with microprice divergence is the JELLY pick-off pattern.',
        narrative:
            'A maker ask was lifted as the perp-oracle basis dislocated, then mean-reverted — a -3.1 bps markout '
            + 'consistent with the JELLY squeeze playbook memory.',
        narrative_source: 'deterministic',
        feature_evidence: { perp_oracle_basis_bps: 8.6, realized_markout_bps: -3.1, toxicity_score: 0.68 },
        model_evidence: { model_name: 'CatBoost markout classifier', risk_score: 0.68 },
        recommended_next_step: 'Skew quotes against the basis until it compresses below 4 bps.',
        created_at: LOOP_START,
    },
];

export const SEED_DECISIONS: PolicyDecision[] = [
    {
        decision_id: 'dec-001',
        case_id: 'case-001',
        recommended_action: 'PULL_RESTING_QUOTES',
        severity: 'critical',
        rationale: 'Sustained critical toxicity with negative markout during a liquidation cascade.',
        confidence: 0.9,
        created_at: LOOP_START,
    },
    {
        decision_id: 'dec-002',
        case_id: 'case-002',
        recommended_action: 'WIDEN_SPREAD',
        severity: 'high',
        rationale: 'Basis dislocation elevates pick-off risk on the ask.',
        confidence: 0.74,
        created_at: LOOP_START,
    },
];

export const SEED_MEMORIES: ImmuneMemory[] = [
    {
        memory_id: 'mem-001',
        threat_name: 'Oct-2025 cascade pick-off',
        description: 'Cascading long liquidations create one-sided OFI that picks off resting bids before spreads widen.',
        scenario_source: 'oct_2025_cascade',
        key_signals: ['one_sided_ofi', 'funding_rate_of_change', 'negative_markout_10s'],
        best_detector: 'CatBoost markout classifier',
        failed_detector: 'OFI-only baseline',
        recommended_detector: 'CatBoost markout classifier + liquidation-intensity feature',
        example_case_id: 'case-001',
        novelty_score: 0.32,
        times_seen: 14,
        created_at: '2025-10-08T09:11:00Z',
        last_seen_at: LOOP_START,
    },
    {
        memory_id: 'mem-002',
        threat_name: 'JELLY basis squeeze',
        description: 'Perp-oracle basis dislocation with microprice divergence picks off makers around the HLP vault.',
        scenario_source: 'jelly_playbook',
        key_signals: ['perp_oracle_basis', 'microprice_divergence'],
        best_detector: 'CatBoost markout classifier',
        failed_detector: 'book-imbalance-only baseline',
        recommended_detector: 'CatBoost markout classifier + basis feature',
        example_case_id: 'case-002',
        novelty_score: 0.51,
        times_seen: 6,
        created_at: '2025-10-09T17:42:00Z',
        last_seen_at: LOOP_START,
    },
    {
        memory_id: 'mem-003',
        threat_name: 'Funding-flip adverse selection',
        description: 'Rapid funding sign-flip precedes one-sided flow and widening spreads.',
        scenario_source: 'funding_flip',
        key_signals: ['funding_rate_of_change', 'spread_bps'],
        best_detector: 'CatBoost markout classifier',
        failed_detector: 'static threshold rule',
        recommended_detector: 'CatBoost markout classifier + funding RoC feature',
        example_case_id: 'case-001',
        novelty_score: 0.4,
        times_seen: 9,
        created_at: '2025-10-09T03:20:00Z',
        last_seen_at: LOOP_START,
    },
];

export const SEED_PROMOTION: PromotionDecision = {
    decision_id: 'promo-001',
    verdict: 'needs_more_data',
    candidate_model: 'CatBoost markout challenger v2.1',
    incumbent_model: 'CatBoost markout champion v2.0',
    rationale: 'Challenger improved calibration and markout lift but missed the PR-AUC bar by a hair under purged CV.',
    metrics: {
        promote_votes: 3,
        reject_votes: 2,
        criteria: {
            markout_lift: { passed: true, detail: '+0.4 bps realized lift vs champion' },
            pr_auc: { passed: false, detail: '0.812 vs 0.821 champion' },
            calibration_brier: { passed: true, detail: 'Brier 0.142 vs 0.151' },
            latency_p95: { passed: true, detail: '0.6 ms < 1 ms budget' },
            no_leakage: { passed: true, detail: 'Purged + embargoed walk-forward CV' },
        },
        candidate: { pr_auc: 0.812, markout_lift_bps: 0.4 },
        candidate_holdout: { pr_auc: 0.805 },
        incumbent: { pr_auc: 0.821, markout_lift_bps: 0.0 },
    },
    created_at: LOOP_START,
};

export const SEED_RECENT_LOOPS: RecentLoop[] = Array.from({ length: 5 }, (_, i) => ({
    loop_id: `loop-2025-10-10-${13 - i}`,
    started_at: `2025-10-10T${String(13 - i).padStart(2, '0')}:04:21Z`,
    duration_ms: 5400 + i * 320,
    aggregate_posture: i === 0 ? 'pull_resting_quotes' : 'widen_spread',
    alert_count: 6 - i,
    case_count: 2,
    new_memory_count: i === 0 ? 1 : 0,
    proposal_name: 'replay-oct-2025-cascade',
}));

export const SEED_LOOP_STATE: LoopState = {
    loop: {
        loop_id: LOOP_ID,
        started_at: LOOP_START,
        duration_ms: 5400,
        aggregate_posture: 'pull_resting_quotes',
        proposal_name: PROPOSAL.name,
        alert_count: 6,
        case_count: SEED_CASES.length,
        new_memory_count: 1,
        agent_runs: SEED_AGENT_RUNS,
        proposal: PROPOSAL,
        cases: SEED_CASES,
        decisions: SEED_DECISIONS,
    },
    memories: SEED_MEMORIES,
    promotion: SEED_PROMOTION,
    recent_loops: SEED_RECENT_LOOPS,
};

export const SEED_MODEL_METRICS: ModelMetric[] = [
    {
        id: 1,
        model_name: 'catboost_markout_champion',
        model_display: 'CatBoost markout champion',
        task_name: 'adverse_selection_10s',
        pr_auc: 0.821,
        auroc: 0.83,
        inference_latency_ms: 0.6,
        extra_metrics: { markout_lift_bps: 0.0, brier: 0.151, false_positive_rate: 0.12 },
        phase: 2,
        rank: 1,
    },
    {
        id: 2,
        model_name: 'catboost_markout_challenger',
        model_display: 'CatBoost markout challenger',
        task_name: 'adverse_selection_10s',
        pr_auc: 0.812,
        auroc: 0.822,
        inference_latency_ms: 0.6,
        extra_metrics: { markout_lift_bps: 0.4, brier: 0.142, false_positive_rate: 0.11 },
        phase: 2,
        rank: 2,
    },
    {
        id: 3,
        model_name: 'ofi_only_baseline',
        model_display: 'OFI-only baseline',
        task_name: 'adverse_selection_10s',
        pr_auc: 0.763,
        auroc: 0.771,
        inference_latency_ms: 0.2,
        extra_metrics: { markout_lift_bps: -0.6, brier: 0.184, false_positive_rate: 0.21 },
        phase: 2,
        rank: 3,
    },
];

export const SEED_BENCHMARK_METRICS: BenchmarkMetric[] = [
    {
        phase: 2,
        title: 'Purged/embargoed walk-forward CV',
        data: {
            folds: 6,
            embargo_minutes: 10,
            mean_pr_auc: 0.812,
            std_pr_auc: 0.019,
            note: 'Labels overlap on the 10s markout horizon, so each test fold is purged + embargoed.',
        },
        created_at: LOOP_START,
        updated_at: LOOP_START,
    },
    {
        phase: 2,
        title: 'Realized markout lift (bps)',
        data: {
            policy: 'widen/withhold when toxicity > tau',
            baseline: 'always-quote',
            lift_bps: 0.4,
            tau: 0.55,
        },
        created_at: LOOP_START,
        updated_at: LOOP_START,
    },
];

export const SEED_TRAINING_RUNS: TrainingRun[] = [
    {
        id: 1,
        model_name: 'CatBoost markout champion v2.0',
        dataset_version: 'gold-btc-perp-2025w40',
        split_summary: 'purged/embargoed walk-forward · 6 folds · 10m embargo',
        pr_auc: 0.821,
        f1: 0.742,
        precision: 0.781,
        recall: 0.708,
        lead_time_ms: 0.6,
        artifact_path: 'reports/v2/markout_champion_card.md',
        created_at: '2025-10-09T22:00:00Z',
    },
    {
        id: 2,
        model_name: 'CatBoost markout challenger v2.1',
        dataset_version: 'gold-btc-perp-2025w41',
        split_summary: 'purged/embargoed walk-forward · 6 folds · 10m embargo',
        pr_auc: 0.812,
        f1: 0.738,
        precision: 0.769,
        recall: 0.71,
        lead_time_ms: 0.6,
        artifact_path: 'reports/v2/markout_challenger_card.md',
        created_at: LOOP_START,
    },
    {
        id: 3,
        model_name: 'OFI-only baseline',
        dataset_version: 'gold-btc-perp-2025w41',
        split_summary: 'purged/embargoed walk-forward · 6 folds · 10m embargo',
        pr_auc: 0.763,
        f1: 0.671,
        precision: 0.69,
        recall: 0.654,
        lead_time_ms: 0.2,
        artifact_path: 'reports/v2/ofi_baseline_card.md',
        created_at: '2025-10-09T20:30:00Z',
    },
];
