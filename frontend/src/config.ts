// Single place for instrument and protocol constants. The model was trained on SOL
// maker fills with a 10 s markout horizon and a 1 bps fee hurdle
// (marketimmune.labels.markout.MarkoutConfig); the live tape must use the same.

export const COIN = 'SOL';
export const SYMBOL = `${COIN}-PERP`;

export const HL_INFO_URL = 'https://api.hyperliquid.xyz/info';
export const HL_WS_URL = 'wss://api.hyperliquid.xyz/ws';

/** Label horizon: a fill is judged by the mid this long after it printed. */
export const HORIZON_MS = 10_000;
/** A fill is "regretted" (toxic) when its maker markout is below -fee. */
export const TOXIC_FEE_BPS = 1.0;
/** Rolling window for the live regret statistics. */
export const STATS_WINDOW_MS = 5 * 60_000;
/** A label's mid must print within this of fill time + horizon (the offline label allows 30 s;
 * the live book prints every few hundred ms, so more than 2 s means a gap). */
export const MAX_LABEL_LAG_MS = 2_000;
/** A fill is scored only with a book at most this old at its time... */
export const MAX_BOOK_AGE_MS = 5_000;
/** ...and an asset context at most this old. */
export const MAX_CTX_AGE_MS = 60_000;
/** A context received at local time L counts as known from exchange time L - (smallest recent
 * local-minus-exchange offset) + this margin. The offset holds the fastest delivery delay
 * (about 230 ms for Hyperliquid's feed), so the margin keeps the join late, never early. */
export const CTX_AVAILABILITY_MARGIN_MS = 500;
/** No book update for this long on an open socket means it has stalled: reconnect. */
export const FEED_STALL_MS = 15_000;
/** A ping unanswered for this long means the socket is dead: reconnect. */
export const PONG_TIMEOUT_MS = 10_000;
export const TAPE_LIMIT = 60;
export const BOOK_DEPTH = 11;

/** Chart intervals offered in the price panel, with their bar length. */
export const CANDLE_INTERVALS = {
    '1m': 60_000,
    '5m': 5 * 60_000,
    '15m': 15 * 60_000,
    '1h': 60 * 60_000,
    '4h': 4 * 60 * 60_000,
} as const;
export type CandleInterval = keyof typeof CANDLE_INTERVALS;
export const DEFAULT_CANDLE_INTERVAL: CandleInterval = '1m';
/** Bars requested when the chart (re)loads an interval. */
export const CANDLE_HISTORY_BARS = 360;

/**
 * Exported by `python -m marketimmune.cli.export_web_model` into frontend/public/model/.
 * Resolved against this module's URL so it works from Vite, a static host, and
 * Django's /static/terminal/ alike (the path is built at runtime so Vite does not
 * try to bundle a file that only exists after training).
 */
export const MODEL_URL = new URL(['..', 'model', 'markout.json'].join('/'), import.meta.url).href;
export const SERVER_POLL_MS = 30_000;
