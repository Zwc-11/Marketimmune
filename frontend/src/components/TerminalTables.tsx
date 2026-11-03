import { memo } from 'react';
import { useServerApi, type HyperliquidBackfillJob } from '../data/serverApi';
import { clockTime, durationMs, fixed, integer, percent, signed, utcDate } from '../lib/format';
import type { ResolvedFill } from '../lib/regret';
import { COMMITTED } from '../lib/report';
import { useMarket } from '../market/useMarket';
import { Empty } from './Panel';
import StatusMark, { type StatusMarkStatus } from './reactbits/StatusMark';

/** Resolved fills never change, so only rows for newly resolved fills render. */
const LogRow = memo(function LogRow({ fill, decimals }: { fill: ResolvedFill; decimals: number }) {
    return (
        <tr>
            <td className="num muted">{clockTime(fill.time)}</td>
            <td className={fill.makerSide === 1 ? 'up' : 'down'}>{fill.makerSide === 1 ? 'Bid' : 'Ask'}</td>
            <td className="num">{fixed(fill.px, decimals)}</td>
            <td className="num">{fixed(fill.sz, 2)}</td>
            <td className="num">{fill.score === null ? '–' : fixed(fill.score, 3)}</td>
            <td className={fill.action === 'withhold' ? 'down' : 'muted'}>
                {fill.action === null ? 'Not scored' : fill.action === 'withhold' ? 'Withhold' : 'Quote'}
            </td>
            <td className={`num ${fill.regret ? 'down' : fill.markoutBps >= 0 ? 'up' : 'muted'}`}>
                {signed(fill.markoutBps, 2)} bps
            </td>
            <td className={fill.regret ? 'down' : 'muted'}>{fill.regret ? 'Regretted' : 'Kept'}</td>
        </tr>
    );
});

export function RegretLog() {
    const resolved = useMarket((s) => s.resolved);
    const decimals = useMarket((s) => s.priceDecimals);
    if (!resolved.length) {
        return (
            <Empty title="No fills resolved yet">
                Each fill settles 10 s after it prints, against the first mid at or after that time.
            </Empty>
        );
    }
    return (
        <table className="grid-table">
            <thead>
                <tr>
                    <th>Time</th>
                    <th title="Which resting side was filled">Rested</th>
                    <th className="num">Price</th>
                    <th className="num">Size</th>
                    <th className="num">p(regret)</th>
                    <th>Decision</th>
                    <th className="num">10 s markout</th>
                    <th>Outcome</th>
                </tr>
            </thead>
            <tbody>
                {resolved.map((fill) => (
                    <LogRow key={fill.id} fill={fill} decimals={decimals} />
                ))}
            </tbody>
        </table>
    );
}

export function FoldsTable() {
    const report = COMMITTED;
    const baseline = report.cvBaseline.folds;
    return (
        <table className="grid-table">
            <thead>
                <tr>
                    <th>Fold</th>
                    <th>Test window (UTC)</th>
                    <th className="num">Train rows</th>
                    <th className="num">Test rows</th>
                    <th className="num">PR-AUC</th>
                    <th className="num">Threshold</th>
                    <th className="num">Lift, model</th>
                    <th className="num">Lift, OFI baseline</th>
                    <th className="num">Quote rate</th>
                </tr>
            </thead>
            <tbody>
                {report.cv.folds.map((fold, i) => (
                    <tr key={fold.fold_id}>
                        <td>{fold.fold_id}</td>
                        <td className="muted num">
                            {utcDate(fold.test_start_ms)} {new Date(fold.test_start_ms).toISOString().slice(11, 16)} to{' '}
                            {new Date(fold.test_end_ms).toISOString().slice(5, 16).replace('T', ' ')}
                        </td>
                        <td className="num">{integer(fold.n_train)}</td>
                        <td className="num">{integer(fold.n_test)}</td>
                        <td className="num">{fixed(fold.pr_auc, 3)}</td>
                        <td className="num">{fixed(fold.decision_threshold, 2)}</td>
                        <td className="num up">{signed(fold.markout_lift_bps, 3)}</td>
                        <td className="num muted">{signed(baseline[i]?.markout_lift_bps, 3)}</td>
                        <td className="num">{percent(fold.quote_rate)}</td>
                    </tr>
                ))}
            </tbody>
            <tfoot>
                <tr>
                    <td colSpan={9} className="faint table-note">
                        Committed run: {report.cv_scheme === 'purged_kfold' ? 'purged k-fold' : 'walk-forward'} CV with
                        a {report.purge_ms / 1000} s purge and {report.embargo_ms / 1000} s embargo. Folds before the
                        last one train on later days too, so the headline number is the forward holdout, not these folds.
                    </td>
                </tr>
            </tfoot>
        </table>
    );
}

const JOB_MARK: Record<HyperliquidBackfillJob['status'], StatusMarkStatus> = {
    planned: 'pending',
    running: 'running',
    succeeded: 'done',
    failed: 'failed',
};

export function BackfillJobs() {
    const { status, backfills } = useServerApi();
    if (status !== 'online') {
        return (
            <Empty title="Backfill jobs live in the Django API">
                Start it with <code>python server/manage.py runserver</code>, then queue a day with{' '}
                <code>python server/manage.py run_hyperliquid_backfill --coin SOL --date 20260601</code>.
            </Empty>
        );
    }
    if (!backfills?.jobs.length) return <Empty title="No backfill jobs recorded yet" />;
    return (
        <table className="grid-table">
            <thead>
                <tr>
                    <th>Status</th>
                    <th>Coin</th>
                    <th>Date</th>
                    <th className="num">Fills</th>
                    <th className="num">Book snapshots</th>
                    <th className="num">Training rows</th>
                    <th className="num">Duration</th>
                    <th>Message</th>
                </tr>
            </thead>
            <tbody>
                {backfills.jobs.map((job) => (
                    <tr key={job.job_id}>
                        <td>
                            <span className="inline-status">
                                <StatusMark status={JOB_MARK[job.status]} />
                                {job.status}
                            </span>
                        </td>
                        <td>{job.coin}</td>
                        <td className="num">{job.date}</td>
                        <td className="num">{integer(job.fills)}</td>
                        <td className="num">{integer(job.book_snapshots)}</td>
                        <td className="num">{integer(job.training_rows)}</td>
                        <td className="num">{durationMs(job.duration_ms)}</td>
                        <td className="muted truncate">{job.message}</td>
                    </tr>
                ))}
            </tbody>
        </table>
    );
}

export function ApiScoredFills() {
    const { status, decisions } = useServerApi();
    if (status !== 'online' || !decisions?.available) {
        return (
            <Empty title="Scored Gold fills come from the Django API">
                With a promoted model configured in <code>.env</code>, the API scores the newest rows of a
                local Gold partition and persists each decision to the audit trail.
            </Empty>
        );
    }
    if (!decisions.decisions.length) return <Empty title="The API returned no scored fills">{decisions.message}</Empty>;
    return (
        <table className="grid-table">
            <thead>
                <tr>
                    <th>Time</th>
                    <th title="Which resting side was filled">Rested</th>
                    <th className="num">Price</th>
                    <th className="num">Size</th>
                    <th className="num">p(regret)</th>
                    <th>Decision</th>
                    <th className="num">10 s markout</th>
                    <th>Top features</th>
                </tr>
            </thead>
            <tbody>
                {decisions.decisions.map((row) => (
                    <tr key={row.decision_id}>
                        <td className="num muted">{clockTime(row.ts_ms)}</td>
                        <td className={row.maker_side === 1 ? 'up' : 'down'}>{row.maker_side === 1 ? 'Bid' : 'Ask'}</td>
                        <td className="num">{fixed(row.px, 3)}</td>
                        <td className="num">{fixed(row.sz, 2)}</td>
                        <td className="num">{fixed(row.calibrated_score, 3)}</td>
                        <td className={row.action === 'withhold_quote' ? 'down' : 'muted'}>
                            {row.action === 'withhold_quote' ? 'Withhold' : 'Quote'}
                        </td>
                        <td className={`num ${row.toxic ? 'down' : 'muted'}`}>
                            {row.markout_bps === null ? '–' : `${signed(row.markout_bps, 2)} bps`}
                        </td>
                        <td className="muted truncate">{row.top_features.join(', ')}</td>
                    </tr>
                ))}
            </tbody>
        </table>
    );
}
