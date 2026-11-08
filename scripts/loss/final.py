import json, glob, collections
import numpy as np, pandas as pd
OUT = '/home/claude/marketimmune/eval/paper/loss/'
F = pd.read_pickle('/tmp/loss/fills_all.pkl')
F = F[F.maker & (F.run != 'live')]
w = lambda g, c: np.average(g[c], weights=g.usd)
H = [0.2, 0.5, 1, 2, 5, 10, 30, 60, 300]
# markout curve by venue and family
cur = []
for (venue, fam), g in list(F.groupby(['venue', 'family'])) + [((v, 'all maker fills'), g) for v, g in F.groupby('venue')]:
    cur.append({'venue': venue, 'family': fam, 'fills': len(g), 'usd_M': round(g.usd.sum() / 1e6, 2), 'spread': round(w(g, 'spread'), 2),
                **{f'mk_{h}s': round(w(g, f'mk{h}'), 2) for h in H}, 'fee': round(w(g, 'fee_bp'), 2)})
C = pd.DataFrame(cur); C.to_csv(OUT + 'markout_curve.csv', index=False)
print(C[C.family == 'all maker fills'].to_string(index=False))
# pre-fill move, correct sign: positive before1s = mid moved toward our resting quote
lab = ['moved away from the quote', 'still (within 0.25 bp)', 'came 0.25-1 bp toward', 'came 1-2 bp toward', 'came over 2 bp toward']
pre = []
for venue, V in F.groupby('venue'):
    b = pd.cut(V.before1s, [-1e9, -0.25, 0.25, 1, 2, 1e9], labels=lab)
    for k, g in V.groupby(b, observed=True):
        pre.append({'venue': venue, 'before_fill': k, 'share': round(len(g) / len(V), 3), 'spread': round(w(g, 'spread'), 2), 'mk_1s': round(w(g, 'mk1'), 2), 'mk_60s': round(w(g, 'mk60'), 2), 'net_60s_after_fee': round(w(g, 'mk60') - w(g, 'fee_bp'), 2)})
P = pd.DataFrame(pre); P.to_csv(OUT + 'pre_fill_move.csv', index=False); print(P.to_string(index=False))
# dollars by component per run (paper_report), excluding the first oversized live run
comp = []
for f in sorted(glob.glob('/tmp/loss/report_*.json')):
    run = f.split('report_')[1][:-5]; r = json.load(open(f)); h = r['hours']
    t = collections.defaultdict(float)
    for s in r['by_strategy']:
        for k, v in s['components_usd_per_hour'].items(): t[k] += v * h
        t['total'] += s['total_usd']; t['notional'] += s['notional_usd']; t['fills'] += s['fills']
    comp.append({'run': run, 'hours': round(h, 1), 'strategies': len(r['by_strategy']), 'fills': int(t['fills']), 'notional_M': round(t['notional'] / 1e6, 1),
                 'total_usd': round(t['total']), 'spread_usd': round(t['spread']), 'move_1s_usd': round(t['adverse_1s']), 'fee_usd': round(t['fee']), 'position_usd': round(t['inventory'])})
D = pd.DataFrame(comp); D.to_csv(OUT + 'dollars_by_run.csv', index=False); print(D.to_string(index=False))
maj = D[D.run.isin(['live-tuned', 'live-mm', 'live-hush', 'live-optimized-20261107T192854Z'])][['total_usd', 'spread_usd', 'move_1s_usd', 'fee_usd', 'position_usd', 'notional_M', 'fills']].sum()
hip = D[D.run == 'live-hip3'][['total_usd', 'spread_usd', 'move_1s_usd', 'fee_usd', 'position_usd', 'notional_M', 'fills']].sum()
print('majors', maj.to_dict()); print('hip3', hip.to_dict())
# by coin and by hour
for venue, V in F.groupby('venue'):
    g = V.groupby('coin').apply(lambda x: pd.Series({'fills': len(x), 'usd_M': x.usd.sum() / 1e6, 'spread': w(x, 'spread'), 'mk60': w(x, 'mk60'), 'net60': w(x, 'mk60') - w(x, 'fee_bp'), 'loss_usd': ((x.mk60 - x.fee_bp) * x.usd / 1e4).sum()}), include_groups=False).sort_values('loss_usd').round(2)
    g.to_csv(OUT + f"by_coin_{'hip3' if venue.startswith('HIP') else 'majors'}.csv")
    h = V.groupby('hour').apply(lambda x: pd.Series({'fills': len(x), 'mk60': w(x, 'mk60'), 'loss_usd': ((x.mk60 - x.fee_bp) * x.usd / 1e4).sum()}), include_groups=False).round(2)
    h.to_csv(OUT + f"by_hour_{'hip3' if venue.startswith('HIP') else 'majors'}.csv")
