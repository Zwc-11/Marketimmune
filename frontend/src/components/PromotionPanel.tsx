import type { PromotionDecision } from '../types';

const PILL: Record<PromotionDecision['verdict'], string> = {
    promote: 'green',
    needs_more_data: 'amber',
    reject: 'red',
};

export function PromotionPanel({ promotion }: { promotion: PromotionDecision }) {
    const criteria = promotion.metrics.criteria ?? {};
    const passed = promotion.metrics.promote_votes ?? 0;
    const total = Object.keys(criteria).length || 5;
    return (
        <div className={`panel ${PILL[promotion.verdict]}`}>
            <div className="row">
                <h2 style={{ margin: 0 }}>
                    Latest Judge Verdict · {promotion.verdict.replace('_', ' ').toUpperCase()}
                </h2>
                <div className="spacer" />
                <span className={`pill ${PILL[promotion.verdict]}`}>
                    {passed} / {total} criteria
                </span>
            </div>
            <p className="mono muted" style={{ marginTop: 6 }}>
                {promotion.candidate_model} vs {promotion.incumbent_model}
            </p>
            <div style={{ marginTop: 10 }}>
                {Object.entries(criteria).map(([name, c]) => (
                    <div key={name} className="criteria-row">
                        <span className={`criteria-mark ${c.passed ? 'pass' : 'fail'}`}>
                            {c.passed ? '✓' : '✗'}
                        </span>
                        <span className="criteria-name">{name}</span>
                        <span className="criteria-detail">{c.detail}</span>
                    </div>
                ))}
            </div>
        </div>
    );
}
