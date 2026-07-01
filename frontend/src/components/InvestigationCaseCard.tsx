import type { InvestigationCase, PolicyDecision } from '../types';

interface Props {
    caseFile: InvestigationCase;
    decision: PolicyDecision | undefined;
}

const ACTION_PILL: Record<string, string> = {
    block_simulated_agent: 'red',
    critical_alert: 'red',
    request_human_review: 'amber',
    warning_alert: 'amber',
    monitor: 'blue',
    add_to_benchmark: 'blue',
    request_retraining: 'blue',
    no_action: 'muted',
};

export function InvestigationCaseCard({ caseFile, decision }: Props) {
    const featureRows = Object.entries(caseFile.feature_evidence)
        .filter(([k]) => !k.startsWith('rationale_source'))
        .slice(0, 8);

    return (
        <div className={`case ${caseFile.severity}`}>
            <div className="case-header">
                <span className="case-id">{caseFile.case_id}</span>
                <span className={`pill ${caseFile.severity === 'critical' ? 'red' : caseFile.severity === 'high' ? 'amber' : 'blue'}`}>
                    {caseFile.severity}
                </span>
            </div>

            <div className="case-title">{caseFile.suspected_behavior}</div>
            <div className="muted" style={{ fontSize: 12 }}>
                {caseFile.explanation}
            </div>

            {caseFile.matched_rules.length > 0 && (
                <div className="row" style={{ marginTop: 8, gap: 4 }}>
                    {caseFile.matched_rules.map((r) => (
                        <span key={r} className="pill muted" style={{ fontSize: 9 }}>
                            {r}
                        </span>
                    ))}
                </div>
            )}

            {caseFile.narrative && (
                <div className="narrative">
                    <div style={{ marginBottom: 6, fontSize: 10, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--cyan)' }}>
                        Analyst narrative{' '}
                        <span className={`pill ${caseFile.narrative_source === 'llm' ? 'blue' : 'muted'}`} style={{ fontSize: 9, marginLeft: 6 }}>
                            {caseFile.narrative_source === 'llm' ? 'narrative engine' : 'deterministic'}
                        </span>
                    </div>
                    {caseFile.narrative}
                </div>
            )}

            <div className="feature-grid">
                {featureRows.map(([k, v]) => (
                    <div key={k}>
                        {k}: <span className="v">{Number(v).toFixed(2)}</span>
                    </div>
                ))}
            </div>

            {decision && (
                <div style={{ marginTop: 10 }}>
                    <span className={`pill ${ACTION_PILL[decision.recommended_action] ?? 'blue'}`}>
                        {decision.recommended_action}
                    </span>
                    <span className="muted" style={{ fontSize: 11, marginLeft: 8 }}>
                        confidence {decision.confidence.toFixed(2)}
                    </span>
                    <p className="muted" style={{ fontSize: 11, marginTop: 4 }}>
                        {decision.rationale}
                    </p>
                </div>
            )}
        </div>
    );
}
