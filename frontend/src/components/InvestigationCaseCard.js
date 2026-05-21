import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
const ACTION_PILL = {
    block_simulated_agent: 'red',
    critical_alert: 'red',
    request_human_review: 'amber',
    warning_alert: 'amber',
    monitor: 'blue',
    add_to_benchmark: 'blue',
    request_retraining: 'blue',
    no_action: 'muted',
};
export function InvestigationCaseCard({ caseFile, decision }) {
    const featureRows = Object.entries(caseFile.feature_evidence)
        .filter(([k]) => !k.startsWith('rationale_source'))
        .slice(0, 8);
    return (_jsxs("div", { className: `case ${caseFile.severity}`, children: [_jsxs("div", { className: "case-header", children: [_jsx("span", { className: "case-id", children: caseFile.case_id }), _jsx("span", { className: `pill ${caseFile.severity === 'critical' ? 'red' : caseFile.severity === 'high' ? 'amber' : 'blue'}`, children: caseFile.severity })] }), _jsx("div", { className: "case-title", children: caseFile.suspected_behavior }), _jsx("div", { className: "muted", style: { fontSize: 12 }, children: caseFile.explanation }), caseFile.matched_rules.length > 0 && (_jsx("div", { className: "row", style: { marginTop: 8, gap: 4 }, children: caseFile.matched_rules.map((r) => (_jsx("span", { className: "pill muted", style: { fontSize: 9 }, children: r }, r))) })), caseFile.narrative && (_jsxs("div", { className: "narrative", children: [_jsxs("div", { style: { marginBottom: 6, fontSize: 10, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--blue)' }, children: ["Analyst narrative", ' ', _jsx("span", { className: `pill ${caseFile.narrative_source === 'llm' ? 'blue' : 'muted'}`, style: { fontSize: 9, marginLeft: 6 }, children: caseFile.narrative_source === 'llm' ? 'narrative engine' : 'deterministic' })] }), caseFile.narrative] })), _jsx("div", { className: "feature-grid", children: featureRows.map(([k, v]) => (_jsxs("div", { children: [k, ": ", _jsx("span", { className: "v", children: Number(v).toFixed(2) })] }, k))) }), decision && (_jsxs("div", { style: { marginTop: 10 }, children: [_jsx("span", { className: `pill ${ACTION_PILL[decision.recommended_action] ?? 'blue'}`, children: decision.recommended_action }), _jsxs("span", { className: "muted", style: { fontSize: 11, marginLeft: 8 }, children: ["confidence ", decision.confidence.toFixed(2)] }), _jsx("p", { className: "muted", style: { fontSize: 11, marginTop: 4 }, children: decision.rationale })] }))] }));
}
