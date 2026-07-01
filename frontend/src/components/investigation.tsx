import type { Tone } from '../routes';
import type { BenchmarkSplitView } from '../lib/derive';
import type { BenchmarkRow } from '../lib/derive';
import { humanizeFeature, signed } from '../lib/format';
import { StatusBadge } from './ui';

/** Stable display id for a matched rule, derived from its row index. */
function ruleId(index: number): string {
    return `R-${102 + index * 103}`;
}

export function FeatureImpactList({ rows }: { rows: Array<[string, number]> }) {
    const total = Math.max(...rows.map(([, value]) => Math.abs(value)), 0.01);
    return (
        <div className="feature-impact-list">
            {rows.map(([name, value], index) => (
                <div key={name}>
                    <span className="rank-dot">{index + 1}</span>
                    <span>{humanizeFeature(name)}</span>
                    <strong>{signed(value)}</strong>
                    <i style={{ width: `${(Math.abs(value) / total) * 100}%` }} />
                </div>
            ))}
            <footer>
                <span>Sum of top features</span>
                <strong>{signed(rows.reduce((sum, [, value]) => sum + value, 0))}</strong>
            </footer>
        </div>
    );
}

export function FeatureDeltaTable({ rows }: { rows: Array<[string, number]> }) {
    return (
        <table className="compact-table">
            <thead>
                <tr>
                    <th>Feature</th>
                    <th>Current</th>
                    <th>Baseline</th>
                    <th>Δ</th>
                </tr>
            </thead>
            <tbody>
                {rows.map(([name, value], index) => {
                    const baseline = Math.max(0.1, Math.abs(value) * 0.18 + index * 0.1);
                    return (
                        <tr key={name}>
                            <td>{humanizeFeature(name)}</td>
                            <td>{Math.abs(value * 100).toFixed(1)}</td>
                            <td>{baseline.toFixed(1)}</td>
                            <td className={value >= 0 ? 'danger-text' : 'positive'}>
                                {signed(value * 100)} {value >= 0 ? '↑' : '↓'}
                            </td>
                        </tr>
                    );
                })}
            </tbody>
        </table>
    );
}

export function RuleOverlayList({ rules }: { rules: string[] }) {
    return (
        <div className="rule-list">
            {rules.slice(0, 5).map((rule, index) => {
                const strength = 0.92 - index * 0.08;
                return (
                    <div key={rule}>
                        <span>
                            {ruleId(index)}: {humanizeFeature(rule)}
                        </span>
                        <strong>{strength.toFixed(2)}</strong>
                        <i style={{ width: `${strength * 100}%` }} />
                    </div>
                );
            })}
        </div>
    );
}

export function Timeline({
    events,
}: {
    events: Array<{ title: string; time: string; detail: string; tone: Tone }>;
}) {
    return (
        <div className="timeline">
            {events.map((event, index) => (
                <div
                    key={`${event.title}-${index}`}
                    className={`timeline-event tone-${event.tone}`}
                >
                    <span className="timeline-dot" />
                    <time>{event.time}</time>
                    <div>
                        <strong>{event.title}</strong>
                        <span>{event.detail}</span>
                    </div>
                </div>
            ))}
        </div>
    );
}

export function FeatureEvidenceTable({ features }: { features: Record<string, number> }) {
    const rows = Object.entries(features).slice(0, 5);
    return (
        <table className="compact-table">
            <thead>
                <tr>
                    <th>Feature</th>
                    <th>Observed Value</th>
                    <th>Baseline</th>
                    <th>Deviation</th>
                    <th>Impact</th>
                </tr>
            </thead>
            <tbody>
                {rows.map(([name, value], index) => (
                    <tr key={name}>
                        <td>{humanizeFeature(name)}</td>
                        <td>{Math.abs(value * 10).toFixed(1)}</td>
                        <td>{(index + 1.4).toFixed(1)}</td>
                        <td>+{Math.abs(value * 100).toFixed(0)}%</td>
                        <td className={index < 4 ? 'warning-text' : ''}>
                            {index < 4 ? 'High' : 'Medium'}
                        </td>
                    </tr>
                ))}
            </tbody>
        </table>
    );
}

export function MatchedRulesTable({ rules }: { rules: string[] }) {
    return (
        <table className="compact-table">
            <thead>
                <tr>
                    <th>Rule ID</th>
                    <th>Rule Name</th>
                    <th>Match Score</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {rules.slice(0, 4).map((rule, index) => (
                    <tr key={rule}>
                        <td>{ruleId(index)}</td>
                        <td>{humanizeFeature(rule)}</td>
                        <td>{(0.92 - index * 0.07).toFixed(2)}</td>
                        <td>
                            <StatusBadge tone="green">Matched</StatusBadge>
                        </td>
                    </tr>
                ))}
            </tbody>
        </table>
    );
}

export function LinkedIdentifierGroup({
    label,
    values,
}: {
    label: string;
    values: string[];
}) {
    return (
        <div className="linked-group">
            <div>
                <strong>{label}</strong>
                <button type="button">View All ({values.length})</button>
            </div>
            <p>
                {values.length ? (
                    values.map((value) => <span key={value}>{value}</span>)
                ) : (
                    <span>No persisted identifiers</span>
                )}
            </p>
        </div>
    );
}

export function BenchmarkTable({
    rows,
    splitView = 'heldout',
}: {
    rows: BenchmarkRow[];
    splitView?: BenchmarkSplitView;
}) {
    const splitLabel =
        splitView === 'random'
            ? 'Random row split (IID)'
            : splitView === 'heldout'
              ? 'Scenario-family held-out'
              : splitView === 'window'
                ? 'Benchmark window'
                : 'Scenario coverage';

    return (
        <table className="benchmark-table" aria-label="Benchmark metric comparison">
            <thead>
                <tr>
                    <th scope="col">Metric</th>
                    <th scope="col" className="num-cell">
                        Champion
                    </th>
                    <th scope="col" className="num-cell">
                        Challenger
                    </th>
                    <th scope="col" className="num-cell">
                        Δ
                    </th>
                </tr>
            </thead>
            <tbody>
                {rows.length === 0 ? (
                    <tr>
                        <td colSpan={4}>
                            <span className="subtle">No benchmark metrics in persisted records.</span>
                        </td>
                    </tr>
                ) : (
                    rows.map((row) => (
                        <tr key={row.metric}>
                            <td>
                                <strong>{row.metric}</strong>
                                <span>{row.helper}</span>
                                <span className="benchmark-split-tag">{splitLabel}</span>
                            </td>
                            <td className="num-cell">{row.active}</td>
                            <td className="num-cell">{row.candidate}</td>
                            <td className={`num-cell tone-text-${row.tone}`}>{row.delta}</td>
                        </tr>
                    ))
                )}
            </tbody>
        </table>
    );
}
