import type { ImmuneMemory } from '../types';

export function MemoryShelf({ memories }: { memories: ImmuneMemory[] }) {
    if (memories.length === 0) {
        return (
            <div className="empty">
                No immune memories yet. Run a few easy loops first.
            </div>
        );
    }
    return (
        <>
            {memories.map((m) => (
                <div className="memory-card" key={m.memory_id}>
                    <div className="head">
                        <strong>{m.threat_name}</strong>
                        <span className="pill blue">novelty {m.novelty_score.toFixed(2)}</span>
                    </div>
                    <div className="desc">{m.description.slice(0, 180)}</div>
                    <div className="meta">
                        best detector: {m.best_detector} · seen {m.times_seen}× ·{' '}
                        signals: {m.key_signals.slice(0, 4).join(', ')}
                    </div>
                </div>
            ))}
        </>
    );
}
