"""Trade-level first look at HIP-3 markets: spread, flow, and the maker's markout per trade at
1/10/60 s against the fill price (what a maker at that price earned before fees)."""
import gzip, glob, json, sys
import numpy as np, pandas as pd
files = sorted(glob.glob(sys.argv[1] + '/hl-*.log.gz'))
bbo, trd, ora = [], [], []
for f in files:
    try:
        for line in gzip.open(f, 'rt'):
            ns, raw = line.split('\t', 1)
            try: m = json.loads(raw)
            except ValueError: continue
            ch = m.get('channel'); d = m.get('data')
            if ch == 'bbo':
                b, a = d['bbo']
                if b and a: bbo.append((d['coin'], d['time'], float(b['px']), float(a['px']), float(b['sz']), float(a['sz'])))
            elif ch == 'trades':
                for x in d:
                    trd.append((x['coin'], x['time'], int(ns) // 1_000_000, float(x['px']), float(x['sz']), 1 if x['side'] == 'B' else -1, x['users'][0 if x['side'] == 'B' else 1], x['users'][1 if x['side'] == 'B' else 0]))
            elif ch == 'activeAssetCtx':
                c = d['ctx']; ora.append((d['coin'], int(ns) // 1_000_000, float(c.get('oraclePx') or 'nan'), float(c.get('markPx') or 'nan')))
    except EOFError:
        pass
B = pd.DataFrame(bbo, columns=['coin', 't', 'bid', 'ask', 'bsz', 'asz']).sort_values('t')
T = pd.DataFrame(trd, columns=['coin', 't', 'local', 'px', 'sz', 'side', 'taker', 'maker']).drop_duplicates(['coin', 't', 'px', 'sz', 'taker', 'maker'])
T = T[T.local - T.t < 5000].sort_values('t')
B['mid'] = (B.bid + B.ask) / 2; B['spread'] = (B.ask - B.bid) / B.mid * 1e4
hours = (B.t.max() - B.t.min()) / 3.6e6
print(f'{hours:.2f} h, {len(B)} bbo, {len(T)} trades')
rows = []
for coin, tc in T.groupby('coin'):
    bc = B[B.coin == coin]
    if len(bc) < 10: continue
    t = bc.t.to_numpy(); mid = bc.mid.to_numpy()
    out = {'coin': coin, 'trades': len(tc), 'usd_h': (tc.px * tc.sz).sum() / hours, 'spread_med': bc.spread.median(),
           'self_trade': (tc.taker == tc.maker).mean()}
    usd = (tc.px * tc.sz).to_numpy()
    for h in (1, 10, 60):
        j = np.searchsorted(t, tc.t.to_numpy() + h * 1000, 'right') - 1
        ok = (tc.t.to_numpy() + h * 1000) <= t[-1]
        mk = -tc.side.to_numpy() * (mid[np.clip(j, 0, len(mid) - 1)] - tc.px.to_numpy()) / tc.px.to_numpy() * 1e4
        out[f'mk{h}'] = np.average(mk[ok], weights=usd[ok]) if ok.any() else np.nan
    # half spread actually earned: fill vs mid just before
    j0 = np.searchsorted(t, tc.t.to_numpy(), 'left') - 1
    pre = mid[np.clip(j0, 0, len(mid) - 1)]
    out['spread_earned'] = np.average(-tc.side.to_numpy() * (pre - tc.px.to_numpy()) / tc.px.to_numpy() * 1e4, weights=usd)
    out['top_maker_share'] = tc.groupby('maker').apply(lambda g: (g.px * g.sz).sum()).max() / usd.sum()
    rows.append(out)
R = pd.DataFrame(rows).sort_values('usd_h', ascending=False)
pd.set_option('display.width', 200)
print(R.round(3).to_string(index=False))
T.to_pickle(sys.argv[1] + '/../trades.pkl'); B.to_pickle(sys.argv[1] + '/../bbo.pkl')
