import json, numpy as np, pandas as pd
w = json.load(open('/home/claude/marketimmune/data/paper/tune-hush2/250x4/tuned/state/wallets.json'))
tot, cnt = w['total'], w['count']
score = lambda a: tot.get(a, 0.0) / (cnt.get(a, 0) + 20.0)
T = pd.read_pickle('/tmp/hip3/trades.pkl'); B = pd.read_pickle('/tmp/hip3/bbo.pkl')
T['score'] = T.taker.map(score); T['n'] = T.taker.map(lambda a: cnt.get(a, 0)); T['usd'] = T.px * T.sz
rows = []
for coin, tc in T.groupby('coin'):
    bc = B[B.coin == coin]; t = bc.t.to_numpy(); mid = bc.mid.to_numpy()
    for h in (10, 60):
        j = np.searchsorted(t, tc.t.to_numpy() + h * 1000, 'right') - 1
        T.loc[tc.index, f'mk{h}'] = -tc.side.to_numpy() * (mid[np.clip(j, 0, len(mid) - 1)] - tc.px.to_numpy()) / tc.px.to_numpy() * 1e4
print('trades', len(T), 'takers', T.taker.nunique(), 'known from majors (>=5 takes):', (T.n >= 5).mean().round(3), 'of trades')
T['grp'] = np.where(T.n < 5, 'unknown', np.where(T.score >= 0.665, 'informed (>=0.665)', 'other known'))
g = T.groupby('grp').apply(lambda x: pd.Series({'trades': len(x), 'usd': x.usd.sum(), 'mk10': np.average(x.mk10, weights=x.usd), 'mk60': np.average(x.mk60, weights=x.usd)}), include_groups=False)
print(g.round(3))
# top takers in HIP-3 by volume and their maker markout
top = T.groupby('taker').apply(lambda x: pd.Series({'trades': len(x), 'usd': x.usd.sum(), 'mk10': np.average(x.mk10, weights=x.usd), 'maj_score': score(x.name), 'maj_n': cnt.get(x.name, 0)}), include_groups=False).sort_values('usd', ascending=False)
print(top.head(12).round(2))
