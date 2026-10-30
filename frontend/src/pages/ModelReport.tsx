import { Empty, Panel } from '../components/Panel';
import CountUp from '../components/reactbits/CountUp';
import { useDjango } from '../data/django';
import { durationMs, fixed, integer, percent, signed, yyyymmdd } from '../lib/format';
import { COMMITTED, COMMITTED_REPORT_PATH, REPRODUCE_COMMAND, type MetricSet } from '../lib/report';

const FEATURE_NOTES: Record<string, string> = {
    sz: 'Fill size',
    maker_side: '+1 maker bought, −1 maker sold',
    fee_bps: 'Fee on the fill',
    l2_spread_bps: 'Touch spread',
    l2_microprice_offset_bps: 'Microprice minus mid',
    l2_top_imbalance: 'Touch size imbalance',
    l2_ofi_event: 'OFI of the last book update',
    l2_ofi_1s: 'OFI summed over 1 s',
    l2_ofi_5s: 'OFI summed over 5 s',
    l2_ofi_10s: 'OFI summed over 10 s',
    fill_vs_mid_bps: 'Fill price vs mid, maker-signed',
    asset_basis_bps: 'Mark minus oracle',
    asset_funding: 'Hourly funding rate',
    asset_open_interest: 'Open interest',
    asset_premium: 'Venue premium',
};

function Headline({ value, decimals, prefix = '', suffix = '', label }: {
    value: number;
    decimals: number;
    prefix?: string;
    suffix?: string;
    label: string;
}) {
    return (
        <div className="headline-stat">
            <span className="headline-value num">
                {prefix}
                <CountUp to={Math.abs(value)} decimals={decimals} duration={0.9} trigger="load" />
                {suffix}
            </span>
            <span className="headline-label">{label}</span>
        </div>
    );
}

function FoldLiftChart() {
    const folds = COMMITTED.cv.folds;
    const baseline = COMMITTED.cvBaseline.folds;
    const max = Math.max(...folds.map((f) => f.markout_lift_bps), ...baseline.map((f) => f.markout_lift_bps), 0.01);
    const width = 520;
    const rowH = 30;
    const scale = (v: number) => (Math.max(0, v) / max) * (width - 150);
    return (
        <svg className="fold-chart" viewBox={`0 0 ${width} ${folds.length * rowH + 8}`} role="img"
            aria-label="Markout lift per cross-validation fold, model versus order-flow baseline">
            {folds.map((fold, i) => {
                const y = i * rowH + 4;
                const b = baseline[i]?.markout_lift_bps ?? 0;
                return (
                    <g key={fold.fold_id}>
                        <text x="0" y={y + 15} className="fold-label">Fold {fold.fold_id}</text>
                        <rect x="56" y={y + 2} height="9" width={scale(fold.markout_lift_bps)} className="bar-model" rx="1" />
                        <rect x="56" y={y + 13} height="9" width={scale(b)} className="bar-base" rx="1" />
                        <text x={62 + scale(fold.markout_lift_bps)} y={y + 10} className="fold-value">
                            {signed(fold.markout_lift_bps, 3)}
                        </text>
                        <text x={62 + scale(b)} y={y + 21} className="fold-value faint-fill">
                            {signed(b, 3)}
                        </text>
                    </g>
                );
            })}
        </svg>
    );
}

function CompareRow({ label, model, raw, base, format }: {
    label: string;
    model: number | null;
    raw: number | null;
    base: number | null;
    format: (v: number | null) => string;
}) {
    return (
        <tr>
            <th scope="row">{label}</th>
            <td className="num">{format(model)}</td>
            <td className="num muted">{format(raw)}</td>
            <td className="num muted">{format(base)}</td>
        </tr>
    );
}

function HoldoutTable() {
    const h = COMMITTED.holdout;
    const b = COMMITTED.holdoutBaseline;
    const f3 = (v: number | null) => fixed(v, 3);
    const rows: { label: string; pick: (m: MetricSet) => number | null; format: (v: number | null) => string }[] = [
        { label: 'PR-AUC', pick: (m) => m.pr_auc, format: f3 },
        { label: 'Brier score', pick: (m) => m.brier, format: f3 },
        { label: 'Expected calibration error', pick: (m) => m.ece, format: f3 },
        { label: 'Markout lift vs quoting all (bps)', pick: (m) => m.markout_lift_bps, format: (v) => signed(v, 3) },
        { label: 'Quote rate', pick: (m) => m.quote_rate, format: (v) => percent(v) },
        { label: 'Withhold threshold', pick: (m) => m.decision_threshold, format: (v) => fixed(v, 2) },
    ];
    const raw = COMMITTED.holdoutRaw;
    return (
        <table className="grid-table compare">
            <thead>
                <tr>
                    <th />
                    <th className="num">CatBoost, calibrated</th>
                    <th className="num">CatBoost, raw</th>
                    <th className="num">10 s OFI baseline</th>
                </tr>
            </thead>
            <tbody>
                {rows.map((row) => (
                    <CompareRow key={row.label} label={row.label} model={row.pick(h)} raw={row.label === 'Withhold threshold' ? null : row.pick(raw)} base={row.pick(b)} format={row.format} />
                ))}
            </tbody>
        </table>
    );
}

function PromotedArtifact() {
    const { status, model } = useDjango();
    if (status !== 'online') {
        return (
            <Empty title="The Django API is not running">
                The numbers on this page come from the committed report. Start the API to also see the
                promoted artifact it serves and a live latency probe.
            </Empty>
        );
    }
    if (!model?.available) return <Empty title="No promoted model configured">{model?.message}</Empty>;
    return (
        <dl className="kv">
            <dt>Model</dt><dd>{model.model_name}</dd>
            <dt>Dataset</dt><dd>{model.dataset_label}</dd>
            <dt>Validation</dt><dd>{model.cv_scheme === 'walk_forward' ? 'Walk-forward' : 'Purged k-fold'}</dd>
            <dt>Threshold</dt><dd className="num">{fixed(model.decision_threshold ?? null, 2)}</dd>
            <dt>Latency p50 / p95</dt>
            <dd className="num">{durationMs(model.smoke_latency?.p50_ms)} / {durationMs(model.smoke_latency?.p95_ms)}</dd>
        </dl>
    );
}

export default function ModelReportPage() {
    const r = COMMITTED;
    const first = yyyymmdd(r.partition_rows[0].date);
    const last = yyyymmdd(r.partition_rows[r.partition_rows.length - 1].date);
    const holdoutDay = yyyymmdd(r.holdout.dates[0]);
    return (
        <div className="report">
            <header className="report-head">
                <h1>Which SOL perp fills will a market maker regret 10 seconds later?</h1>
                <p className="muted">
                    A CatBoost classifier over Hyperliquid maker fills. A fill counts as regretted when the
                    mid 10 s later puts the maker more than 1 bps under water. Trained on {integer(r.training_rows)} fills
                    from {first} to {last}, scored on {holdoutDay}, a day it never saw.
                </p>
            </header>

            <section className="headline-row" aria-label={`Held-out results for ${holdoutDay}`}>
                <Headline value={r.holdoutLiftVsBaselineBps} decimals={3} prefix="+" suffix=" bps" label="Per fill over the order-flow baseline" />
                <Headline value={r.holdout.markout_lift_bps} decimals={3} prefix="+" suffix=" bps" label="Per fill over quoting every fill" />
                <Headline value={r.holdout.pr_auc} decimals={3} label={`PR-AUC (baseline ${fixed(r.holdoutBaseline.pr_auc, 3)})`} />
                <Headline value={r.holdout.brier} decimals={3} label={`Brier (baseline ${fixed(r.holdoutBaseline.brier, 3)})`} />
                <Headline value={r.holdout.quote_rate * 100} decimals={1} suffix="%" label="Fills still quoted" />
            </section>

            <div className="report-grid">
                <Panel title={`Held-out day, ${holdoutDay}`} className="span-2">
                    <HoldoutTable />
                    <p className="table-note faint">
                        {integer(r.holdout.n_rows)} fills. Thresholds were chosen on training-period out-of-fold
                        predictions ({r.policy.threshold_count}-point grid, quote rate between{' '}
                        {percent(r.policy.min_quote_rate, 0)} and {percent(r.policy.max_quote_rate, 0)}) and then frozen.
                    </p>
                </Panel>

                <Panel title="How it was validated">
                    <ul className="protocol">
                        <li>
                            Cross-validation: {r.cv_scheme === 'purged_kfold' ? 'purged k-fold' : 'walk-forward'}, {r.n_splits} folds,
                            {' '}{r.purge_ms / 1000} s purge and {r.embargo_ms / 1000} s embargo around each test window, so no
                            training fill's 10 s label overlaps a test fill.
                        </li>
                        <li>
                            In this committed run, four of the five folds also train on days after their test
                            window. The holdout day is the clean out-of-time number; it trains only on earlier days.
                        </li>
                        <li>
                            New runs default to anchored walk-forward (<code>--cv-scheme walk_forward</code>), where every
                            fold trains strictly on earlier fills.
                        </li>
                        <li>Isotonic calibration is fit per fold on the newest 20% of that fold's training rows.</li>
                        <li>The baseline is a fixed rule: 10 s OFI signed to the maker's side, squashed to a probability.</li>
                    </ul>
                </Panel>

                <Panel title="Markout lift by fold" actions={<span className="legend"><i className="sw model" />Model <i className="sw base" />OFI baseline</span>}>
                    <FoldLiftChart />
                </Panel>

                <Panel title="Training data">
                    <table className="grid-table">
                        <thead><tr><th>Day (UTC)</th><th>Role</th><th className="num">Maker fills</th></tr></thead>
                        <tbody>
                            {r.partition_rows.map((p) => (
                                <tr key={p.date}><td className="num">{yyyymmdd(p.date)}</td><td className="muted">Train</td><td className="num">{integer(p.rows)}</td></tr>
                            ))}
                            {r.holdout.partition_rows.map((p) => (
                                <tr key={`h${p.date}`}><td className="num">{yyyymmdd(p.date)}</td><td className="up">Holdout</td><td className="num">{integer(p.rows)}</td></tr>
                            ))}
                        </tbody>
                    </table>
                </Panel>

                <Panel title={`Features (${r.feature_columns.length})`}>
                    <table className="grid-table">
                        <tbody>
                            {r.feature_columns.map((name) => (
                                <tr key={name}><td><code>{name}</code></td><td className="muted">{FEATURE_NOTES[name] ?? ''}</td></tr>
                            ))}
                        </tbody>
                    </table>
                </Panel>

                <Panel title="Model">
                    <dl className="kv">
                        <dt>Learner</dt><dd>CatBoost, {r.catboost.iterations} trees, depth {r.catboost.depth}, learning rate {r.catboost.learning_rate}</dd>
                        <dt>Seed</dt><dd className="num">{r.catboost.seed}</dd>
                        <dt>Fit time, 6 fits</dt><dd className="num">{fixed(r.fit_elapsed_s, 1)} s</dd>
                        <dt>Single-fill latency p95</dt><dd className="num">{durationMs(r.latency_p95_ms)}</dd>
                        <dt>CV PR-AUC</dt><dd className="num">{fixed(r.cv.pr_auc, 3)} (baseline {fixed(r.cvBaseline.pr_auc, 3)})</dd>
                        <dt>CV lift vs quoting all</dt><dd className="num">{signed(r.cv.markout_lift_bps, 3)} bps</dd>
                    </dl>
                </Panel>

                <Panel title="Promoted artifact (Django)">
                    <PromotedArtifact />
                </Panel>

                <Panel title="Reproduce" className="span-2">
                    <p className="muted">Exact rerun of this report (needs the local Gold partitions):</p>
                    <code className="command block">{REPRODUCE_COMMAND}</code>
                    <p className="faint">Source artifact: <code>{COMMITTED_REPORT_PATH}</code></p>
                </Panel>
            </div>
        </div>
    );
}
