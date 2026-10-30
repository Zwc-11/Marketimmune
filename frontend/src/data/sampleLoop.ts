// A labelled sample immune-loop run for when the Django API is not running (static
// builds, first checkout). The UI shows it only behind an explicit "Show sample run"
// action and badges every view "Sample". Agent outputs below are illustrative; the
// only model numbers quoted are the committed SOL benchmark's.

import type {
    AgentRunSummary,
    ImmuneMemory,
    InvestigationCase,
    LoopState,
    PolicyDecision,
} from '../types';

const LOOP_ID = 'sample-loop-sol-0601';
const T0 = Date.parse('2026-06-01T14:02:11Z');
const at = (ms: number) => new Date(T0 + ms).toISOString();

function run(
    agent: string,
    goal: string,
    offsetMs: number,
    durationMs: number,
    tool: string,
    summary: string,
    decision?: { observation: string; decision: string; confidence: number },
): AgentRunSummary {
    return {
        run_id: `${LOOP_ID}-${agent.toLowerCase()}`,
        agent_name: agent,
        goal,
        started_at: at(offsetMs),
        finished_at: at(offsetMs + durationMs),
        duration_ms: durationMs,
        success: true,
        error: '',
        output: {},
        linked_artifacts: {},
        tool_call_count: 1,
        trace_count: decision ? 1 : 0,
        tool_calls: [
            {
                tool,
                arguments: { coin: 'SOL', horizon: '10s' },
                duration_ms: Math.round(durationMs * 0.7),
                result_summary: summary,
                occurred_at: at(offsetMs + 5),
            },
        ],
        decision_traces: decision
            ? [{ goal, ...decision, evidence: {}, occurred_at: at(offsetMs + durationMs) }]
            : [],
    };
}

const RUNS: AgentRunSummary[] = [
    run('RedTeam', 'Pick a SOL-PERP window with clustered maker pick-offs', 0, 410,
        'select_episode', 'Chose 14:00–14:10 UTC: one-sided flow after a funding print', {
            observation: 'Ask-side depth thinned twice inside 30 s',
            decision: 'replay the window for the sentinel',
            confidence: 0.74,
        }),
    run('Sentinel', 'Score maker fills with the promoted markout model', 420, 160,
        'score_fills', 'Scored 1,284 fills; 212 at or above the 0.30 withhold threshold', {
            observation: '212 fills crossed p(regret) ≥ 0.30',
            decision: 'open an investigation on the densest cluster',
            confidence: 0.81,
        }),
    run('Investigator', 'Explain the worst cluster', 590, 1_180,
        'build_case', 'Cluster: taker buys into a thinning ask, 10 s OFI strongly positive', {
            observation: 'Realized 10 s maker markout −3.1 bps across the cluster',
            decision: 'classify as high-severity adverse selection',
            confidence: 0.77,
        }),
    run('Policy', 'Choose a quoting control', 1_780, 90,
        'emit_command', 'Recommended: widen ask by 1 tick while 10 s OFI > 0.6', {
            observation: 'Withholding at 0.30 keeps about a quarter of fills quoted',
            decision: 'widen-and-skew rather than pull',
            confidence: 0.7,
        }),
    run('Memory', 'Record the episode', 1_880, 70,
        'upsert_memory', 'Reinforced "post-funding ask thinning" (seen 3 times)'),
];

const CASES: InvestigationCase[] = [
    {
        case_id: 'sample-case-1',
        alert_id: 'sample-alert-1',
        suspected_behavior: 'Taker buys into a thinning ask after a funding print',
        severity: 'high',
        confidence: 0.77,
        observation: '38 maker sells in 9 s, 31 regretted at 10 s',
        timeline: [],
        matched_rules: ['ofi_10s_one_sided', 'ask_depth_drop'],
        explanation: 'Positive 10 s OFI and a shrinking ask queue preceded the pick-offs.',
        narrative:
            'Resting asks were lifted repeatedly while the ask queue shrank; the mid rose ' +
            'about 3 bps over the next 10 s, so most maker sells marked out negative.',
        narrative_source: 'deterministic',
        feature_evidence: { l2_ofi_10s: 0.71, l2_top_imbalance: 0.42, fill_vs_mid_bps: 0.6 },
        model_evidence: {},
        recommended_next_step: 'Widen the ask by one tick while 10 s OFI stays above 0.6',
        created_at: at(1_770),
    },
];

const DECISIONS: PolicyDecision[] = [
    {
        decision_id: 'sample-decision-1',
        case_id: 'sample-case-1',
        recommended_action: 'widen_and_skew',
        severity: 'high',
        rationale: 'Pulling quotes would cede the queue; a one-tick widen covers the drift.',
        confidence: 0.7,
        created_at: at(1_870),
    },
];

const MEMORIES: ImmuneMemory[] = [
    {
        memory_id: 'sample-memory-1',
        threat_name: 'Post-funding ask thinning',
        description: 'Ask queue thins after a funding print; takers lift into it.',
        scenario_source: 'sample',
        key_signals: ['l2_ofi_10s', 'l2_top_imbalance', 'asset_funding'],
        best_detector: 'catboost_markout_SOL_10s',
        failed_detector: 'event_ofi_10s',
        recommended_detector: 'catboost_markout_SOL_10s',
        example_case_id: 'sample-case-1',
        novelty_score: 0.32,
        times_seen: 3,
        created_at: at(1_900),
        last_seen_at: at(1_900),
    },
];

export const SAMPLE_LOOP_STATE: LoopState = {
    loop: {
        loop_id: LOOP_ID,
        started_at: at(0),
        duration_ms: 1_950,
        aggregate_posture: 'elevated',
        proposal_name: 'sol-post-funding-thinning',
        alert_count: 212,
        case_count: CASES.length,
        new_memory_count: 1,
        agent_runs: RUNS,
        proposal: null,
        cases: CASES,
        decisions: DECISIONS,
    },
    memories: MEMORIES,
    promotion: null,
    recent_loops: [],
};
