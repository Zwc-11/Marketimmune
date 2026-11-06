import { useMemo, useState } from 'react';
import { PaperChart } from '../components/PaperChart';
import { Empty, Panel, Stat } from '../components/Panel';
import {
    registeredOf,
    strategyColors,
    strategyGroup,
    useCoinPrices,
    usePaperState,
    type PaperCoin,
    type PaperDecision,
    type PaperQuote,
    type PaperState,
} from '../data/paper';
import { clockTime, fixed, integer, signed } from '../lib/format';

const PRICE_COIN = 'BTC';
const CHART_EXTRA = ['touch', 'zgap@0.25', 'kelly@0.5', 'reservation@1', 'hawkes@3'];
const GROUP_LABEL = {
    candidate: 'Registered',
    control: 'Control',
    advanced: 'Exploratory',
    baseline: 'December',
    maker: 'Market maker',
    wallets: 'Gap + wallets',
} as const;

function usd(value: number | null | undefined, decimals = 0): string {
    if (value === null || value === undefined || !Number.isFinite(value)) return '–';
    const text = fixed(Math.abs(value), decimals);
    return value < 0 ? `−$${text}` : `$${text}`;
}

const tone = (v: number | null | undefined) => (v === null || v === undefined ? 'muted' : v > 0 ? 'up' : v < 0 ? 'down' : '');

function elapsed(ms: number): string {
    const s = Math.max(0, Math.floor(ms / 1000));
    return [Math.floor(s / 3600), Math.floor(s / 60) % 60, s % 60].map((v) => String(v).padStart(2, '0')).join(':');
}

function Header({ state, prices }: { state: PaperState; prices: [number, number][] }) {
    const age = state.last_event_ms ? state.now_ms - state.last_event_ms : Infinity;
    const delay = state.feed_delay_ms.hl_top?.[1];
    const btc = state.coins.find((c) => c.coin === PRICE_COIN)?.mid ?? null;
    const first = prices[0]?.[1];
    const change = btc !== null && first ? (btc / first - 1) * 100 : null;
    const clock = state.clock;
    return (
        <div className="market-header paper-header">
            <div className="symbol">
                <span className="symbol-name">Paper trading</span>
                <span className="symbol-venue">Hyperliquid perps · simulated fills · no order is sent</span>
            </div>
            <dl className="header-stats">
                <div className="header-stat">
                    <dt title="Hyperliquid BTC perp mid; change since the first price this run (or this page) has">BTC</dt>
                    <dd className="num">
                        {btc === null ? '–' : `$${btc.toLocaleString('en-US', { maximumFractionDigits: 1 })}`}{' '}
                        {change !== null && <span className={tone(change)}>{`${change >= 0 ? '+' : '−'}${fixed(Math.abs(change), 2)}%`}</span>}
                    </dd>
                </div>
                <div className="header-stat">
                    <dt>Feed</dt>
                    <dd>
                        <span className={`chip ${age < 3000 ? 'chip-live' : ''}`}>{age < 3000 ? 'Live' : `Stale ${Math.round(age / 1000)} s`}</span>
                    </dd>
                </div>
                <div className="header-stat">
                    <dt>Running</dt>
                    <dd className="num">{state.started_ms ? elapsed(state.now_ms - state.started_ms) : '–'}</dd>
                </div>
                <div className="header-stat">
                    <dt>Segment</dt>
                    <dd className="num">{state.segment}</dd>
                </div>
                <div className="header-stat">
                    <dt title="Median time from Hyperliquid's block to this machine">Hyperliquid delay</dt>
                    <dd className="num">{delay === undefined ? '–' : `${integer(delay)} ms`}</dd>
                </div>
                <div className="header-stat">
                    <dt title="This machine's clock against Coinbase's timestamps. Paper orders are timed on it against Hyperliquid's blocks, so an uncorrected fast clock delays every order by its offset.">
                        Clock
                    </dt>
                    <dd className={`num ${clock?.corrected ? '' : 'down'}`}>
                        {clock?.corrected
                            ? `corrected ${integer(clock.offset_ms ?? 0)} ms`
                            : clock?.measured_ms != null
                              ? `${integer(clock.measured_ms - 15)} ms off`
                              : 'not checked'}
                    </dd>
                </div>
                <div className="header-stat">
                    <dt>Order latency</dt>
                    <dd className="num">{state.settings.latency_ms === undefined ? '–' : `${state.settings.latency_ms} ms`}</dd>
                </div>
                <div className="header-stat">
                    <dt>Reconnects</dt>
                    <dd className="num">{state.reconnects}</dd>
                </div>
                <div className="header-stat">
                    <dt>Fees</dt>
                    <dd className="num">
                        {state.settings.fees_bps ? `${fixed(state.settings.fees_bps.maker, 1)} / ${fixed(state.settings.fees_bps.taker, 1)} bp` : '–'}
                    </dd>
                </div>
            </dl>
        </div>
    );
}

function Summary({ state }: { state: PaperState }) {
    const by = Object.fromEntries(state.strategies.map((s) => [s.strategy, s]));
    const BEST = registeredOf(state)[0];
    const best = by[BEST];
    const ctl = by.touch;
    const diff = best && ctl ? best.pnl - ctl.pnl : null;
    return (
        <div className="paper-stats">
            <Stat label={`Best candidate, ${BEST}`} value={usd(best?.pnl, 2)} tone={best && best.pnl < 0 ? 'down' : 'up'} hint="The run's first registered strategy; summed over the coins" />
            <Stat label="Per filled dollar" value={best?.bps == null ? '–' : `${signed(best.bps, 2)} bps`} />
            <Stat label="Control, touch" value={usd(ctl?.pnl, 2)} tone={ctl && ctl.pnl < 0 ? 'down' : 'up'} hint="Always quotes both sides at the best price" />
            <Stat label="Best vs control, per hour" value={diff === null || state.hours < 0.01 ? '–' : usd(diff / state.hours)} tone={diff !== null && diff < 0 ? 'down' : 'up'} />
            <Stat label="Hours" value={fixed(state.hours, 2)} />
        </div>
    );
}

function Leaderboard({ state, onPick, picked }: { state: PaperState; onPick: (s: string) => void; picked: string }) {
    const registered = registeredOf(state);
    const colors = strategyColors(registered);
    return (
        <table className="grid-table paper-board">
            <thead>
                <tr>
                    <th>Strategy</th>
                    <th>Group</th>
                    <th className="num">PnL</th>
                    <th className="num">Per hour</th>
                    <th className="num" title="PnL per filled dollar">bps</th>
                    <th className="num">Fills</th>
                    <th className="num" title="Sum over coins of the absolute position">Gross position</th>
                    <th className="num" title="Sum over coins of the signed position: the bet on the market's direction">Net position</th>
                    <th className="num" title="Orders plus cancels per minute: what Hyperliquid's rate limit counts">Actions / min</th>
                </tr>
            </thead>
            <tbody>
                {state.strategies.map((s) => (
                    <tr
                        key={s.strategy}
                        className={s.strategy === picked ? 'selected' : undefined}
                        tabIndex={0}
                        onClick={() => onPick(s.strategy)}
                        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onPick(s.strategy)}
                    >
                        <td>
                            <span className="swatch" style={{ background: colors[s.strategy] ?? 'var(--rule-strong)' }} />
                            {s.strategy}
                        </td>
                        <td className="muted">{GROUP_LABEL[strategyGroup(s.strategy, registered)]}</td>
                        <td className={`num ${tone(s.pnl)}`}>{usd(s.pnl, 2)}</td>
                        <td className={`num ${tone(s.per_hour)}`}>{usd(s.per_hour)}</td>
                        <td className={`num ${tone(s.bps)}`}>{s.bps == null ? '–' : signed(s.bps, 2)}</td>
                        <td className="num">{integer(s.fills)}</td>
                        <td className="num">{usd(s.gross_usd)}</td>
                        <td className="num">{usd(s.net_usd)}</td>
                        <td className="num">{s.actions_per_min == null ? '–' : integer(s.actions_per_min)}</td>
                    </tr>
                ))}
            </tbody>
        </table>
    );
}

function Quote({ quote, side }: { quote: PaperQuote | null; side: 'bid' | 'ask' }) {
    if (!quote) return <span className="muted">pulled</span>;
    return (
        <span className={side === 'bid' ? 'up' : 'down'}>
            {quote.px}
            <span className="muted">{quote.live ? (quote.queue == null ? '' : ` · ${usd(quote.queue * quote.px)} ahead`) : ' · in flight'}</span>
        </span>
    );
}

function Decisions({ coins, decisions, picked }: { coins: PaperCoin[]; decisions: PaperDecision[]; picked: string }) {
    const mine = new Map(decisions.filter((d) => d.strategy === picked).map((d) => [d.coin, d]));
    return (
        <table className="grid-table paper-decisions">
            <thead>
                <tr>
                    <th>Coin</th>
                    <th className="num">Mid</th>
                    <th className="num">Spread</th>
                    <th className="num" title="Coinbase mid over Hyperliquid's, less its 5-minute average">Gap</th>
                    <th className="num" title="Gap over its own volatility">Gap z</th>
                    <th className="num" title="Expected Hyperliquid move over 10 s from the gap (recursive least squares)">10 s forecast</th>
                    <th className="num" title="The walk-forward model's next-second move">Model 1 s</th>
                    <th className="num" title="Taker arrival intensity over its 10-minute level (Hawkes kernel)">Buy / sell burst</th>
                    <th>Bid</th>
                    <th>Ask</th>
                    <th className="num">Position</th>
                    <th className="num">PnL</th>
                    <th>Why</th>
                </tr>
            </thead>
            <tbody>
                {coins.map((c) => {
                    const d = mine.get(c.coin);
                    return (
                        <tr key={c.coin}>
                            <td>{c.coin}</td>
                            <td className="num">{c.mid === null ? '–' : c.mid.toPrecision(6)}</td>
                            <td className="num">{fixed(c.spread_bps, 2)}</td>
                            <td className={`num ${tone(c.gap_bps)}`}>{signed(c.gap_bps, 2)}</td>
                            <td className={`num ${tone(c.gap_z)}`}>{signed(c.gap_z, 2)}</td>
                            <td className={`num ${tone(c.forecast_10s_bps)}`}>{signed(c.forecast_10s_bps, 2)}</td>
                            <td className={`num ${tone(c.model_1s_bps)}`}>{signed(c.model_1s_bps, 2)}</td>
                            <td className="num">
                                {fixed(c.buy_burst, 1)} / {fixed(c.sell_burst, 1)}
                            </td>
                            <td>{d ? <Quote quote={d.bid} side="bid" /> : '–'}</td>
                            <td>{d ? <Quote quote={d.ask} side="ask" /> : '–'}</td>
                            <td className={`num ${tone(d?.position_usd)}`}>{usd(d?.position_usd)}</td>
                            <td className={`num ${tone(c.pnl[picked])}`}>{usd(c.pnl[picked], 2)}</td>
                            <td className="paper-why">{d?.reason ?? '–'}</td>
                        </tr>
                    );
                })}
            </tbody>
        </table>
    );
}

const SIDES = { both: 'Both sides', bid: 'Bid only', ask: 'Ask only', none: 'No quotes' } as const;

function DecisionLog({ state, picked }: { state: PaperState; picked: string }) {
    const rows = state.decision_log.filter((e) => e.strategy === picked).slice(0, 40);
    if (!rows.length) return <Empty title="No changes yet">Each time this strategy starts or stops quoting a side, the change and its reason appear here.</Empty>;
    return (
        <table className="grid-table">
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Coin</th>
                    <th>Now quoting</th>
                    <th>Why</th>
                </tr>
            </thead>
            <tbody>
                {rows.map((e, i) => (
                    <tr key={`${e.t_ms}-${e.coin}-${i}`}>
                        <td className="num muted">{clockTime(e.t_ms)}</td>
                        <td>{e.coin}</td>
                        <td className={e.sides === 'bid' ? 'up' : e.sides === 'ask' ? 'down' : ''}>{SIDES[e.sides]}</td>
                        <td className="paper-why">{e.reason}</td>
                    </tr>
                ))}
            </tbody>
        </table>
    );
}

function Tape({ state, picked }: { state: PaperState; picked: string }) {
    const rows = state.tape.filter((f) => f.strategy === picked).slice(0, 40);
    if (!rows.length) return <Empty title="No fills yet">Paper fills for this strategy appear here as real trades reach its quotes.</Empty>;
    return (
        <table className="grid-table">
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Coin</th>
                    <th>Side</th>
                    <th className="num">Price</th>
                    <th className="num">Size</th>
                </tr>
            </thead>
            <tbody>
                {rows.map((f, i) => (
                    <tr key={`${f.t_ms}-${f.coin}-${i}`}>
                        <td className="num muted">{clockTime(f.t_ms)}</td>
                        <td>{f.coin}</td>
                        <td className={f.side > 0 ? 'up' : 'down'}>{f.side > 0 ? 'Bought' : 'Sold'}</td>
                        <td className="num">{f.px}</td>
                        <td className="num">{usd(f.usd)}</td>
                    </tr>
                ))}
            </tbody>
        </table>
    );
}

export default function PaperPage() {
    const status = usePaperState();
    const [chosen, setPicked] = useState('');
    const registered = status.kind === 'live' ? registeredOf(status.state) : [];
    const key = registered.join(',');
    const focus = useMemo(() => [...registered, ...CHART_EXTRA.filter((s) => !registered.includes(s))], [key]);
    const colors = useMemo(() => strategyColors(registered), [key]);
    const picked = chosen || registered[0] || '';
    const prices = useCoinPrices(status.kind === 'live' ? status.state : null, PRICE_COIN);
    const last = prices[prices.length - 1]?.[0];
    const price = useMemo(() => ({ label: PRICE_COIN, points: prices }), [prices, last]);
    if (status.kind !== 'live') {
        return (
            <div className="paper">
                <Panel title="Paper trading">
                    <Empty title={status.kind === 'connecting' ? 'Connecting to the paper run' : 'No paper run on this machine'}>
                        Start one, then reload:
                        <pre className="command">
                            python -m marketimmune.cli.paper_trade --out data/paper/live --hours 24 --segment-hours 2 --serve 8765 --web frontend/dist
                        </pre>
                        It reads Hyperliquid and Coinbase's public feeds and matches paper orders against real trades. No order is sent.
                    </Empty>
                </Panel>
            </div>
        );
    }
    const { state } = status;
    return (
        <div className="paper">
            <div className="paper-head">
                <Header state={state} prices={prices} />
                <Summary state={state} />
            </div>
            <Panel
                className="paper-equity"
                title="Cumulative PnL by strategy"
                actions={<span className="faint">Right: PnL, each segment marked to the mid at its end · left, dotted: BTC</span>}
            >
                <PaperChart history={state.history} focus={focus} price={price} colors={colors} />
            </Panel>
            <Panel className="paper-leaders" title="Leaderboard" actions={<span className="faint">Select a row to follow it below</span>}>
                <Leaderboard state={state} onPick={setPicked} picked={picked} />
            </Panel>
            <Panel className="paper-live" title={`Live decisions · ${picked}`} actions={<span className="faint">Signals per coin and what the strategy is quoting now</span>}>
                <Decisions coins={state.coins} decisions={state.decisions} picked={picked} />
            </Panel>
            <Panel className="paper-log" title="Decision log" actions={<span className="faint">{picked}</span>}>
                <DecisionLog state={state} picked={picked} />
            </Panel>
            <Panel className="paper-tape" title="Fills" actions={<span className="faint">{picked}</span>}>
                <Tape state={state} picked={picked} />
            </Panel>
        </div>
    );
}
