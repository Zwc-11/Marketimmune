import type { CSSProperties } from 'react';
import type { MemoryCardShape } from '../lib/derive';
import { noveltyLabel, toneForNovelty } from '../lib/derive';
import { shortId } from '../lib/format';
import { Icon } from './Icon';
import { DataPanel, KeyValueList, StatusBadge } from './ui';
import type { Tone } from '../routes';

export function MemoryCard({
    memory,
    index,
}: {
    memory: MemoryCardShape;
    index: number;
}) {
    const noveltyTone: Tone = toneForNovelty(memory.novelty_score);
    return (
        <DataPanel
            className="memory-card"
            style={{ '--delay': `${index * 60}ms` } as CSSProperties}
        >
            <div className="memory-card-head">
                <h3>{memory.threat_name}</h3>
                <StatusBadge tone={noveltyTone}>{noveltyLabel(memory.novelty_score)}</StatusBadge>
            </div>
            <span>Key Signals</span>
            <div className="tag-row">
                {memory.key_signals.slice(0, 3).map((signal) => (
                    <span key={signal}>{signal}</span>
                ))}
                <span>+1</span>
            </div>
            <KeyValueList
                rows={[
                    [
                        'Best Detector',
                        <>
                            <Icon name="shield" /> {memory.best_detector}
                        </>,
                    ],
                    [
                        'Failed Detector',
                        <>
                            <Icon name="close-circle" /> {memory.failed_detector}
                        </>,
                    ],
                    [
                        'Recommended',
                        <>
                            <Icon name="shield" /> {memory.recommended_detector}
                        </>,
                    ],
                ]}
            />
            <div className="memory-stats">
                <span>
                    Novelty Score{' '}
                    <strong className={memory.novelty_score >= 0.5 ? 'warning-text' : 'positive'}>
                        {memory.novelty_score.toFixed(2)}
                    </strong>
                </span>
                <span>
                    Times Seen <strong>{memory.times_seen}</strong>
                </span>
                <span>
                    Example Case <strong>{shortId(memory.example_case_id)}</strong>
                </span>
            </div>
        </DataPanel>
    );
}
