import { SYMBOL } from '../config';
import { useServerApi } from '../data/serverApi';
import type { FeedStatus } from '../market/feed';
import { useMarket, useNow } from '../market/useMarket';
import StatusMark, { type StatusMarkStatus } from './reactbits/StatusMark';

const STALE_MS = 15_000;

function feedMark(status: FeedStatus, ageMs: number | null): { mark: StatusMarkStatus; text: string } {
    if (status === 'live' && ageMs !== null && ageMs > STALE_MS) {
        return { mark: 'failed', text: `No messages for ${Math.round(ageMs / 1000)} s` };
    }
    if (status === 'live') return { mark: 'done', text: 'Hyperliquid stream live' };
    if (status === 'reconnecting') return { mark: 'running', text: 'Reconnecting to Hyperliquid' };
    return { mark: 'running', text: 'Connecting to Hyperliquid' };
}

export function StatusBar() {
    const status = useMarket((s) => s.status);
    const lastMessageAt = useMarket((s) => s.lastMessageAt);
    const model = useMarket((s) => s.model);
    const api = useServerApi();
    const now = useNow();
    const age = lastMessageAt === null ? null : now - lastMessageAt;
    const { mark, text } = feedMark(status, age);

    return (
        <footer className="statusbar" aria-label="Connection status">
            <span className="status-item">
                <StatusMark status={mark} />
                {text}
            </span>
            <span className="status-item faint">{SYMBOL}</span>
            {age !== null && (
                <span className="status-item faint num">
                    Last message {Math.max(0, Math.round(age / 100) / 10).toFixed(1)} s ago
                </span>
            )}
            <span className="status-item">
                {model.state === 'ready'
                    ? `Model ${model.name ?? 'loaded'} (${model.treeCount} trees)`
                    : model.state === 'loading'
                      ? 'Loading model artifact'
                      : 'No web model artifact; fills are labelled but not scored'}
            </span>
            <span className="status-item status-right">
                {api.status === 'online' ? 'API connected' : api.status === 'checking' ? 'Checking API' : 'API offline'}
            </span>
        </footer>
    );
}
