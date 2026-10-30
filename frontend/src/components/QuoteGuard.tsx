import { STATS_WINDOW_MS } from '../config';
import { bps, fixed, integer, percent, signed, yyyymmdd } from '../lib/format';
import { COMMITTED } from '../lib/report';
import { useMarket } from '../market/useMarket';
import { Stat } from './Panel';
import { RegretMatrix } from './RegretMatrix';
import Counter from './reactbits/Counter';

const EXPORT_COMMAND =
    'python -m marketimmune.cli.export_web_model --model <model>.cbm --report <report>.json';

function LatestDecision() {
    const model = useMarket((s) => s.model);
    const tape = useMarket((s) => s.tape);
    const latest = tape.find((fill) => fill.score !== null) ?? null;
    const threshold = model.state === 'ready' ? (model.meta.decision_threshold ?? 0.5) : null;
    const action = latest?.action ?? null;

    return (
        <div className="guard-decision">
            <div className="segmented" role="status" aria-live="off">
                <span className={`segment ${action === 'quote' ? 'on-bid' : ''}`}>Quote</span>
                <span className={`segment ${action === 'withhold' ? 'on-ask' : ''}`}>Withhold</span>
            </div>
            {model.state === 'ready' ? (
                <>
                    <div className="guard-score">
                        <span className="muted">p(regret) of the last fill</span>
                        <span className={action === 'withhold' ? 'down' : 'fg'}>
                            {latest?.score != null ? (
                                <Counter
                                    value={latest.score}
                                    decimals={3}
                                    duration={0.25}
                                    bounce={0}
                                    motionBlur={false}
                                    intro={false}
                                    fontSize={20}
                                    fontWeight={500}
                                    textColor="currentColor"
                                />
                            ) : (
                                '–'
                            )}
                        </span>
                    </div>
                    <div className="score-rail" aria-hidden="true">
                        <span className="score-threshold" style={{ left: `${(threshold ?? 0) * 100}%` }} />
                        {latest?.score != null && (
                            <span className="score-dot" style={{ left: `${latest.score * 100}%` }} />
                        )}
                    </div>
                    <p className="guard-note faint">
                        Withhold when p ≥ {fixed(threshold, 2)}. Features are rebuilt in the browser
                        from the live book; their cadence can differ from the training archive.
                    </p>
                </>
            ) : (
                <div className="guard-missing">
                    <p className="muted">
                        {model.state === 'loading'
                            ? 'Loading the exported model…'
                            : model.state === 'error'
                              ? `The model artifact did not load: ${model.message}`
                              : 'No exported model in this build, so fills are labelled but not scored. Export one after training:'}
                    </p>
                    {model.state === 'missing' && <code className="command">{EXPORT_COMMAND}</code>}
                </div>
            )}
        </div>
    );
}

function LiveStats() {
    const stats = useMarket((s) => s.stats);
    const scored = stats.scored > 0;
    return (
        <section className="guard-section" aria-label="Live regret statistics">
            <h3 className="guard-heading">Live labels</h3>
            <RegretMatrix />
            <h4 className="guard-subheading">Last {STATS_WINDOW_MS / 60_000} minutes</h4>
            <div className="stat-grid">
                <Stat label="Resolved fills" value={integer(stats.resolved)} />
                <Stat label="Waiting on 10 s" value={integer(stats.pending)} />
                <Stat
                    label="Regret rate"
                    hint="Share of maker fills whose 10 s markout was below −1 bps"
                    value={percent(stats.regretRate)}
                    tone={stats.regretRate !== null && stats.regretRate > 0.5 ? 'down' : undefined}
                />
                <Stat
                    label="Mean maker markout"
                    value={bps(stats.meanMarkoutBps)}
                    tone={stats.meanMarkoutBps === null ? undefined : stats.meanMarkoutBps >= 0 ? 'up' : 'down'}
                />
                {scored && (
                    <>
                        <Stat label="Withheld" value={`${integer(stats.withheld)} of ${integer(stats.scored)}`} />
                        <Stat
                            label="Policy lift"
                            hint="Mean per-fill markout with withheld fills counted as 0, minus quoting every fill"
                            value={bps(stats.liftBps)}
                            tone={stats.liftBps === null ? undefined : stats.liftBps >= 0 ? 'up' : 'down'}
                        />
                        <Stat label="Withhold precision" hint="Withheld fills that were regretted" value={percent(stats.withholdPrecision)} />
                        <Stat label="Regret recall" hint="Regretted fills the model withheld" value={percent(stats.regretRecall)} />
                    </>
                )}
            </div>
        </section>
    );
}

function CommittedBenchmark() {
    const report = COMMITTED;
    const holdoutDay = yyyymmdd(report.holdout.dates[0] ?? '');
    const first = yyyymmdd(report.partition_rows[0]?.date ?? '');
    const last = yyyymmdd(report.partition_rows[report.partition_rows.length - 1]?.date ?? '');
    return (
        <section className="guard-section" aria-label="Committed benchmark">
            <h3 className="guard-heading">Held-out day {holdoutDay}</h3>
            <p className="guard-lead">
                <span className="guard-lead-value up num">{signed(report.holdoutLiftVsBaselineBps, 3)} bps</span>
                <span className="muted">per fill over the order-flow baseline, on a day the model never saw</span>
            </p>
            <div className="stat-grid">
                <Stat label="PR-AUC" value={`${fixed(report.holdout.pr_auc, 3)} vs ${fixed(report.holdoutBaseline.pr_auc, 3)}`} hint="CatBoost vs the 10 s OFI baseline" />
                <Stat label="Brier" value={fixed(report.holdout.brier, 3)} />
                <Stat label="Lift vs quoting all" value={bps(report.holdout.markout_lift_bps, 3)} tone="up" />
                <Stat label="Quote rate" value={percent(report.holdout.quote_rate)} />
                <Stat label="Training fills" value={integer(report.training_rows)} hint={`${first} to ${last}`} />
                <Stat label="Holdout fills" value={integer(report.holdout.n_rows)} />
            </div>
            <a className="text-link" href="#/model">
                Open the model report
            </a>
        </section>
    );
}

export function QuoteGuard() {
    return (
        <div className="guard">
            <LatestDecision />
            <LiveStats />
            <CommittedBenchmark />
        </div>
    );
}
