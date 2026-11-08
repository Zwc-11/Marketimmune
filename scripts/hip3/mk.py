import sys, numpy as np, pandas as pd
run = sys.argv[1]; strats = sys.argv[2].split(',')
F = pd.read_json(run + '/fills.jsonl', lines=True); M = pd.read_parquet(run + '/mids.parquet')
F = F[F.strategy.isin(strats)]
out = []
for coin, fc in F.groupby('coin'):
    mc = M[M.coin == coin].sort_values('t_ms'); t = mc.t_ms.to_numpy(); mid = mc.mid.to_numpy()
    r = fc.copy()
    for h in (1, 60, 300, 1800):
        j = np.searchsorted(t, r.t_ms.to_numpy() + h * 1000, 'right') - 1
        r[f'mk{h}'] = r.side * (mid[np.clip(j, 0, len(mid) - 1)] - r.px) / r.px * 1e4
    r['usd'] = r.px * r.qty; out.append(r)
F = pd.concat(out)
for s, G in F.groupby('strategy'):
    print(s.ljust(36), len(G), ' '.join(f'mk{h}={np.average(G[f"mk{h}"], weights=G.usd):+.2f}' for h in (1, 60, 300, 1800)))
    by = G.groupby('coin').apply(lambda g: pd.Series({'fills': len(g), 'usd': g.usd.sum(), 'mk60': np.average(g.mk60, weights=g.usd), 'mk300': np.average(g.mk300, weights=g.usd)}), include_groups=False).sort_values('usd', ascending=False)
    print(by.head(6).round(2).to_string())
