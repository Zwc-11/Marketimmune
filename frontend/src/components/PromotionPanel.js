import { jsxs as _jsxs, jsx as _jsx } from "react/jsx-runtime";
const PILL = {
    promote: 'green',
    needs_more_data: 'amber',
    reject: 'red',
};
export function PromotionPanel({ promotion }) {
    const criteria = promotion.metrics.criteria ?? {};
    const passed = promotion.metrics.promote_votes ?? 0;
    const total = Object.keys(criteria).length || 5;
    return (_jsxs("div", { className: `panel ${PILL[promotion.verdict]}`, children: [_jsxs("div", { className: "row", children: [_jsxs("h2", { style: { margin: 0 }, children: ["Latest Judge Verdict \u00B7 ", promotion.verdict.replace('_', ' ').toUpperCase()] }), _jsx("div", { className: "spacer" }), _jsxs("span", { className: `pill ${PILL[promotion.verdict]}`, children: [passed, " / ", total, " criteria"] })] }), _jsxs("p", { className: "mono muted", style: { marginTop: 6 }, children: [promotion.candidate_model, " vs ", promotion.incumbent_model] }), _jsx("div", { style: { marginTop: 10 }, children: Object.entries(criteria).map(([name, c]) => (_jsxs("div", { className: "criteria-row", children: [_jsx("span", { className: `criteria-mark ${c.passed ? 'pass' : 'fail'}`, children: c.passed ? '✓' : '✗' }), _jsx("span", { className: "criteria-name", children: name }), _jsx("span", { className: "criteria-detail", children: c.detail })] }, name))) })] }));
}
