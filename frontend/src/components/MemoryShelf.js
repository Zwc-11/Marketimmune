import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
export function MemoryShelf({ memories }) {
    if (memories.length === 0) {
        return (_jsx("div", { className: "empty", children: "No immune memories yet. Run a few easy loops first." }));
    }
    return (_jsx(_Fragment, { children: memories.map((m) => (_jsxs("div", { className: "memory-card", children: [_jsxs("div", { className: "head", children: [_jsx("strong", { children: m.threat_name }), _jsxs("span", { className: "pill blue", children: ["novelty ", m.novelty_score.toFixed(2)] })] }), _jsx("div", { className: "desc", children: m.description.slice(0, 180) }), _jsxs("div", { className: "meta", children: ["best detector: ", m.best_detector, " \u00B7 seen ", m.times_seen, "\u00D7 \u00B7", ' ', "signals: ", m.key_signals.slice(0, 4).join(', ')] })] }, m.memory_id))) }));
}
