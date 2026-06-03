import type { ProductData } from '../routes';
import { Icon } from '../components/Icon';
import {
    DataPanel,
    EmptyState,
    KeyValueList,
    LoadingState,
    StatusBadge,
} from '../components/ui';
import {
    FeatureEvidenceTable,
    LinkedIdentifierGroup,
    MatchedRulesTable,
    Timeline,
} from '../components/investigation';
import { riskLabel, timelineFromCase, toneForRisk } from '../lib/derive';
import {
    cleanText,
    formatTimestamp,
    metricValue,
    relativeTime,
    sentenceCase,
    shortId,
    truncate,
} from '../lib/format';

export function InvestigationScreen({ data, loading }: { data: ProductData; loading: boolean }) {
    const loop = data.loopState?.loop ?? null;
    const caseFile = loop?.cases[0] ?? null;
    const decision = loop?.decisions.find((item) => item.case_id === caseFile?.case_id) ?? null;

    if (loading && !caseFile) return <LoadingState label="Loading investigation case" />;
    if (!caseFile) {
        return (
            <EmptyState
                title="No investigation case"
                body="Run the immune loop to create a persisted case file."
            />
        );
    }

    const timeline = timelineFromCase(caseFile);
    const confidenceTone = toneForRisk(caseFile.confidence);
    const confidenceLabel = riskLabel(caseFile.confidence);
    const linkedAlertIds = Array.from(
        new Set([caseFile.alert_id, ...(caseFile.timeline ?? []).map((row) => String(row.alert_id ?? ''))]),
    ).filter(Boolean);
    const linkedEventIds = Array.from(
        new Set((caseFile.timeline ?? []).map((row) => String(row.event_id ?? row.linked_event_id ?? ''))),
    ).filter(Boolean);
    return (
        <section className="screen-stack">
            <a className="back-link" href="#/risk">
                <Icon name="chevron-left" /> Back to Investigations
            </a>
            <DataPanel className="case-strip">
                <div className="case-strip-cell">
                    <span>Case ID</span>
                    <strong>{shortId(caseFile.case_id)}</strong>
                    <small>Opened: {formatTimestamp(caseFile.created_at)}</small>
                    <small>
                        Status: Open <span className="status-dot green" />
                    </small>
                </div>
                <div className="case-strip-cell wide">
                    <span>Suspected Behavior</span>
                    <strong>{caseFile.suspected_behavior}</strong>
                    <small>{caseFile.explanation || caseFile.observation}</small>
                </div>
                <div className="case-strip-cell">
                    <span>Severity</span>
                    <strong
                        className={
                            caseFile.severity === 'critical' ? 'danger-text' : 'warning-text'
                        }
                    >
                        {sentenceCase(caseFile.severity)} •
                    </strong>
                    <small>Requires Review</small>
                </div>
                <div className="case-strip-cell">
                    <span>Confidence</span>
                    <strong className="positive">
                        {caseFile.confidence.toFixed(2)}{' '}
                        <StatusBadge tone={confidenceTone}>{confidenceLabel}</StatusBadge>
                    </strong>
                    <small>Model Confidence</small>
                </div>
                <div className="case-strip-cell">
                    <span>Policy Decision</span>
                    <strong>
                        {decision ? sentenceCase(decision.recommended_action) : 'Pending'}
                    </strong>
                    <small>
                        {decision
                            ? `From persisted PolicyAgent record ${shortId(decision.decision_id)}`
                            : 'No PolicyAgent decision persisted for this case'}
                    </small>
                </div>
            </DataPanel>

            <div className="investigation-grid">
                <DataPanel title="Observation">
                    <p>
                        {truncate(
                            cleanText(
                                caseFile.narrative || caseFile.explanation || caseFile.observation,
                            ),
                            720,
                        )}
                    </p>
                    <p>
                        <strong>Key Takeaway:</strong>{' '}
                        {truncate(
                            cleanText(decision?.rationale ?? caseFile.recommended_next_step),
                            150,
                        )}
                    </p>
                    <StatusBadge tone="green">Behavioral Anomaly Detected</StatusBadge>
                </DataPanel>
                <DataPanel title="Feature Evidence">
                    <FeatureEvidenceTable features={caseFile.feature_evidence} />
                    <a className="panel-link" href="#/risk">
                        View All Features <Icon name="chevron" />
                    </a>
                </DataPanel>
                <DataPanel title="Matched Rules">
                    <MatchedRulesTable rules={caseFile.matched_rules} />
                    <a className="panel-link" href="#/risk">
                        View All Rules <Icon name="chevron" />
                    </a>
                </DataPanel>
                <DataPanel title="Timeline of Events">
                    <Timeline events={timeline} />
                    <a className="secondary-action full" href="#/audit">
                        <Icon name="calendar" /> View Full Timeline <Icon name="chevron" />
                    </a>
                </DataPanel>
                <DataPanel title="Model Evidence">
                    <KeyValueList
                        rows={[
                            ['Model Verdict', caseFile.suspected_behavior],
                            [
                                'Model Version',
                                String(
                                    caseFile.model_evidence.model_version ??
                                        caseFile.model_evidence.model_name ??
                                        '-',
                                ),
                            ],
                            ['Score', caseFile.confidence.toFixed(2)],
                            ['Percentile', metricValue(Number(caseFile.model_evidence.percentile))],
                            [
                                'Top Contributing Signals',
                                caseFile.matched_rules.slice(0, 3).join(', ') || '-',
                            ],
                        ]}
                    />
                    <a className="panel-link" href="#/models">
                        View Model Explanation <Icon name="chevron" />
                    </a>
                </DataPanel>
                <DataPanel title="Linked Identifiers">
                    <LinkedIdentifierGroup
                        label="Alert IDs"
                        values={
                            linkedAlertIds.length
                                ? linkedAlertIds.map((value) => `ALT-${value}`)
                                : ['-']
                        }
                    />
                    {linkedEventIds.length > 0 && (
                        <LinkedIdentifierGroup
                            label="Event IDs"
                            values={linkedEventIds.map((value) => shortId(value))}
                        />
                    )}
                    <LinkedIdentifierGroup
                        label="Case ID"
                        values={[shortId(caseFile.case_id)]}
                    />
                    {decision && (
                        <LinkedIdentifierGroup
                            label="Decision ID"
                            values={[shortId(decision.decision_id)]}
                        />
                    )}
                </DataPanel>
            </div>

            <DataPanel className="next-step-panel">
                <div className="recommend-icon">
                    <Icon name="shield" />
                </div>
                <div>
                    <span>Recommended Next Step</span>
                    <strong>{caseFile.recommended_next_step}</strong>
                    <p>{cleanText(caseFile.explanation || caseFile.observation)}</p>
                </div>
                <div className="rationale">
                    <span>Policy Rationale</span>
                    <p>
                        {decision?.rationale ||
                            'No PolicyAgent decision is persisted for this case yet.'}
                    </p>
                </div>
                <a className="secondary-action" href="#/audit">
                    <Icon name="trend" /> View Full Audit Trail <Icon name="chevron" />
                </a>
            </DataPanel>
            <div className="case-footer">
                <span>Case persisted by InvestigatorAgent</span>
                <span>{formatTimestamp(caseFile.created_at)}</span>
                <span>Loaded: {relativeTime(caseFile.created_at)}</span>
                <span>Case ID: {shortId(caseFile.case_id)}</span>
            </div>
        </section>
    );
}
