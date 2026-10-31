// The committed benchmark artifact, bundled at build time so the model page works
// without Django. When the API is up, its promoted-model health payload is shown
// alongside; numbers never come from anywhere else. Only the fields the UI shows
// are read.

import committed from '../../../eval/markout_sol_10s/hyperliquid_markout_SOL_20260527_20260531_holdout_20260601.json';
import { yyyymmdd } from './format';

export const COMMITTED_REPORT_PATH =
    'eval/markout_sol_10s/hyperliquid_markout_SOL_20260527_20260531_holdout_20260601.json';

export const REPRODUCE_COMMAND =
    'git checkout 8f731c0 && python -m marketimmune.cli.train --coin SOL --dates 20260527..20260531 ' +
    '--holdout-date 20260601 --horizon 10s --iterations 150 --n-splits 5 --cv-scheme purged_kfold';

interface FoldRow {
    fold_id: number;
    n_train: number;
    n_test: number;
    test_start_ms: number;
    test_end_ms: number;
    decision_threshold: number;
    pr_auc: number;
    markout_lift_bps: number;
    quote_rate: number;
}

export interface MetricSet {
    n_rows: number;
    pr_auc: number;
    brier: number;
    ece: number;
    markout_lift_bps: number;
    quote_rate: number;
    decision_threshold: number | null;
    folds: FoldRow[];
}

interface BenchmarkReport {
    cv_scheme: string;
    n_splits: number;
    purge_ms: number;
    embargo_ms: number;
    training_rows: number;
    feature_columns: string[];
    partition_rows: { date: string; rows: number }[];
    latency_p95_ms: number;
    fit_elapsed_s: number;
    catboost: { iterations: number; learning_rate: number; depth: number; seed: number };
    cv: MetricSet;
    cvBaseline: MetricSet;
    policy: { min_quote_rate: number; max_quote_rate: number; threshold_count: number };
    holdout: MetricSet & { dates: string[]; partition_rows: { date: string; rows: number }[] };
    holdoutRaw: MetricSet;
    holdoutBaseline: MetricSet;
    holdoutLiftVsBaselineBps: number;
    /** YYYY-MM-DD labels for the first and last training day and the held-out day. */
    trainFirstDay: string;
    trainLastDay: string;
    holdoutDay: string;
}

type Json = Record<string, unknown>;

function metricSet(raw: Json): MetricSet {
    return {
        n_rows: Number(raw.n_rows),
        pr_auc: Number(raw.pr_auc),
        brier: Number(raw.brier),
        ece: Number(raw.ece),
        markout_lift_bps: Number(raw.markout_lift_bps),
        quote_rate: Number(raw.quote_rate),
        decision_threshold: raw.decision_threshold === null ? null : Number(raw.decision_threshold),
        // Cross-validated sets carry per-fold rows; holdout sets do not.
        folds: (raw.folds as FoldRow[] | undefined) ?? [],
    };
}

function normalizeReport(raw: Json): BenchmarkReport {
    const holdout = raw.holdout_split as Json;
    const policy = raw.policy as Json;
    const partitions = raw.partition_rows as BenchmarkReport['partition_rows'];
    const holdoutDates = holdout.dates as string[];
    return {
        // Reports that predate the cv_scheme field were produced with purged k-fold.
        cv_scheme: String(raw.cv_scheme ?? 'purged_kfold'),
        n_splits: Number(raw.n_splits),
        purge_ms: Number(raw.purge_ms),
        embargo_ms: Number(raw.embargo_ms),
        training_rows: Number(raw.training_rows),
        feature_columns: raw.feature_columns as string[],
        partition_rows: partitions,
        latency_p95_ms: Number(raw.latency_p95_ms),
        fit_elapsed_s: Number(raw.fit_elapsed_s),
        catboost: raw.catboost as BenchmarkReport['catboost'],
        cv: metricSet(raw),
        cvBaseline: metricSet((raw.baselines as Record<string, Json>).event_ofi),
        policy: {
            min_quote_rate: Number(policy.min_quote_rate),
            max_quote_rate: Number(policy.max_quote_rate),
            threshold_count: (policy.threshold_grid as number[]).length,
        },
        holdout: {
            ...metricSet(holdout),
            dates: holdoutDates,
            partition_rows: holdout.partition_rows as { date: string; rows: number }[],
        },
        holdoutRaw: metricSet(holdout.uncalibrated as Json),
        holdoutBaseline: metricSet((holdout.baselines as Record<string, Json>).event_ofi),
        holdoutLiftVsBaselineBps: Number(
            (holdout.baseline_comparison as Record<string, Json>).event_ofi.markout_lift_bps,
        ),
        trainFirstDay: yyyymmdd(partitions[0].date),
        trainLastDay: yyyymmdd(partitions[partitions.length - 1].date),
        holdoutDay: yyyymmdd(holdoutDates[0]),
    };
}

export const COMMITTED = normalizeReport(committed as unknown as Json);
