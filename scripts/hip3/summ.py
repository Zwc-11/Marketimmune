import json, sys, collections
import pandas as pd
run = sys.argv[1]
r = json.load(open(run + '_report.json'))
E = pd.read_json(run + '/equity.jsonl', lines=True)
tot = E.groupby(['t_ms', 'strategy']).equity.sum().unstack()
t0, t1 = tot.index.min(), tot.index.max(); mid = (t0 + t1) / 2
h1 = tot[tot.index <= mid].iloc[-1] - 0; h2 = tot.iloc[-1] - tot[tot.index <= mid].iloc[-1]
hrs = (t1 - t0) / 3.6e6
summ = json.load(open(run + '/summary.json'))
orders = collections.Counter()
for x in summ['instances']:
    orders[x['strategy']] += x.get('actions', 0)
print(f"hours {r['hours']}")
rows = []
for s in r['by_strategy']:
    c = s['components_bps']
    opu = orders[s['strategy']] / s['notional_usd'] if s['notional_usd'] else float('nan')
    rows.append((s['usd_per_hour'], s['strategy'], s['fills'], round(s['notional_usd']), s['usd_per_hour_ci95'], s['bps'], c.get('spread'), c.get('adverse_1s'), c.get('adverse_60s'), c.get('inventory'), round(h1.get(s['strategy'], 0) / (hrs / 2), 2), round(h2.get(s['strategy'], 0) / (hrs / 2), 2), round(opu, 2)))
print(f"{'strategy':34s} {'fills':>5s} {'notional':>8s} {'$/h':>7s} {'ci95':>16s} {'bp':>6s} {'spr':>6s} {'adv1':>6s} {'adv60':>6s} {'inv':>6s} {'1st$/h':>7s} {'2nd$/h':>7s} {'ord/$':>6s}")
for u, s, f, n, ci, bp, sp, a1, a60, inv, a, b, o in sorted(rows, reverse=True):
    print(f"{s[:34]:34s} {f:5d} {n:8d} {u:7.2f} {str(ci):>16s} {bp:6.2f} {sp:6.2f} {a1:6.2f} {a60:6.2f} {inv:6.2f} {a:7.2f} {b:7.2f} {o:6.2f}")
