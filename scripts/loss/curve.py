"""Every live paper fill on the PC: markout curve, by family, coin, hour, and what the price did just before."""
import glob, json, sys
import numpy as np, pandas as pd
G = '/mnt/user-data/uploads/Crypto Data/paper'
RUNS = ['live', 'live-tuned', 'live-mm', 'live-hush', 'live-optimized-20261107T192854Z', 'live-hip3']
H = [0.2, 0.5, 1, 2, 5, 10, 30, 60, 300]
def family(s):
    k = s.split('@')[0]
    if k in ('touch', 'improve'): return 'touch / improve (join the best price)'
    if k in ('mm', 'reservation', 'kelly', 'hawkes'): return 'textbook MM (mm, reservation, kelly, hawkes)'
    if k in ('gap', 'zgap', 'guard') or s.startswith('improve+gap'): return 'Coinbase-gap pull (gap, zgap, guard)'
    if k in ('model', 'immune', 'optimal'): return 'model quoters (model, immune, optimal)'
    if k == 'hush': return 'deep + wallet gate (hush)'
    if k == 'taker': return 'taker'
    return k
rows = []
for run in RUNS:
    for seg in sorted(glob.glob(f'{G}/{run}/seg-*')):
        try:
            F = pd.read_json(seg + '/fills.jsonl', lines=True); M = pd.read_parquet(seg + '/mids.parquet')
        except (ValueError, FileNotFoundError):
            continue
        if F.empty: continue
        for coin, fc in F.groupby('coin'):
            mc = M[M.coin == coin].sort_values('t_ms'); t = mc.t_ms.to_numpy(); mid = mc.mid.to_numpy()
            if len(t) < 10: continue
            ft = fc.t_ms.to_numpy(); px = fc.px.to_numpy(); sd = fc.side.to_numpy()
            r = fc[['coin', 'strategy', 't_ms', 'side', 'px', 'qty', 'fee_rate']].copy()
            j0 = np.clip(np.searchsorted(t, ft, 'left') - 1, 0, len(t) - 1)
            r['spread'] = sd * (mid[j0] - px) / px * 1e4                       # earned against the mid before the fill
            jb = np.clip(np.searchsorted(t, ft - 1000, 'right') - 1, 0, len(t) - 1)
            r['before1s'] = -sd * (mid[j0] - mid[jb]) / px * 1e4                # move toward the quote in the second before (negative = price came to us)
            for h in H:
                j = np.clip(np.searchsorted(t, ft + h * 1000, 'right') - 1, 0, len(t) - 1)
                r[f'mk{h}'] = sd * (mid[j] - px) / px * 1e4                     # maker markout vs fill price (spread included), before fee
            r['run'] = run; r['venue'] = 'HIP-3 (0.3 bp fee)' if run == 'live-hip3' else 'majors (1.5 bp fee)'
            rows.append(r)
F = pd.concat(rows, ignore_index=True)
F['usd'] = F.px * F.qty
F['maker'] = F.fee_rate < (0.0002 if True else 0)
F.loc[F.venue.str.startswith('HIP'), 'maker'] = F.fee_rate < 0.00005
F['fee_bp'] = F.fee_rate * 1e4
F['family'] = F.strategy.map(family)
F['hour'] = pd.to_datetime(F.t_ms, unit='ms').dt.hour
F.to_pickle('/tmp/loss/fills_all.pkl')
w = lambda g, c: np.average(g[c], weights=g.usd)
print('fills', len(F), 'maker share', round(F.maker.mean(), 3), 'notional $M', round(F.usd.sum() / 1e6, 1))
first = F.run == 'live'
for venue in F.venue.unique():
    V = F[(F.venue == venue) & F.maker & ~first]
    print(f'\n== {venue}: maker fills {len(V)}, ${V.usd.sum()/1e6:.1f}M  (first live run excluded: other sizes, clock fault)')
    print('markout vs fill price, bp (all maker fills):', ' '.join(f'{h}s {w(V, f"mk{h}"):+.2f}' for h in H), '| spread', f'{w(V, "spread"):+.2f}', '| fee', f'{w(V, "fee_bp"):.2f}')
    for fam, g in V.groupby('family'):
        print(f'  {fam:46s} {len(g):6d} fills  spread {w(g,"spread"):+.2f}  ' + ' '.join(f'{h}s {w(g, f"mk{h}"):+.2f}' for h in (0.5, 1, 10, 60, 300)))
