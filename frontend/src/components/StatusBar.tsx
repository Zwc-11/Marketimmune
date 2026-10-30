import { useServerApi } from '../data/serverApi';
import { SYMBOL } from '../config';
import { useMarket, useNow } from '../market/useMarket';
import StatusMark, { type StatusMarkStatus } from './reactbits/StatusMark';

function feedMark(status: string, ageMs: number | null): { mark: StatusMarkStatus; text: string } {
    if (status === 'live' && ageMs !== null && ageMs > 15_000) {
        return { mark: 'failed', text: `No messages for ${Math.round(ageMs / 1000)} s` };
    }
    if (status === 'live') return { mark: 'done', text: 'Hyperliquid stream live' };
    if (status === 'reconnecting') return { mark: 'running', text: 'Reconnecting to Hyperliquid' };
    return { mark: 'running', text: 'Connecting to Hyperliquid' };
}

export function StatusBar() {
    const feed = useMarket((s) => s.feed);
    const model = useMarket((s) => s.model);
    const api = useServerApi();
    const now = useNow();
    const age = feed.lastMessageAt === null ? null : now - feed.lastMessageAt;
    const { mark, text } = feedMark(feed.status, age);

    return (
        <footer className="statusbar" aria-label="Connection status">
            <span className="status-item">
                <StatusMark status={mark} size={12} strokeWidth={2} doneColor="var(--bid)" errorColor="var(--ask)" />
                {text}
            </span>
            <span className="status-item faint">{SYMBOL}</span>
            {age !== null && <span className="status-item faint num">Last message {Math.max(0, Math.round(age / 100) / 10).toFixed(1)} s ago</span>}
            <span className="status-item">
                {model.state === 'ready'
                    ? `Model ${model.meta.model_name ?? 'loaded'} (${model.treeCount} trees)`
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
