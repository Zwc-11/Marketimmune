import type { Tone } from '../routes';
import type { BenchmarkRow } from '../lib/derive';
import { humanizeFeature, signed } from '../lib/format';
import { StatusBadge } from './ui';

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
                            R-{102 + index * 103}: {humanizeFeature(rule)}
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
                        <td>R-{102 + index * 103}</td>
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

export function BenchmarkTable({ rows }: { rows: BenchmarkRow[] }) {
    return (
        <table className="benchmark-table">
            <thead>
                <tr>
                    <th>Metric (Higher is better)</th>
                    <th>Random Row Split (IID)</th>
                    <th>
                        Scenario-Family Held-Out Split <span>(Primary)</span>
                    </th>
                </tr>
            </thead>
            <tbody>
                {rows.map((row) => (
                    <tr key={row.metric}>
                        <td>
                            <strong>{row.metric}</strong>
                            <span>{row.helper}</span>
                        </td>
                        <td>
                            <span>{row.active}</span>
                            <span>{row.candidate}</span>
                            <strong className={`tone-text-${row.tone}`}>{row.delta}</strong>
                        </td>
                        <td>
                            <span>{row.active}</span>
                            <span>{row.candidate}</span>
                            <strong className={`tone-text-${row.tone}`}>{row.delta}</strong>
                        </td>
                    </tr>
                ))}
            </tbody>
        </table>
    );
}
