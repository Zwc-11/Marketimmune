"""Per strategy and coin: $ in each half of a run and in total, from equity.jsonl (marked PnL after fees)."""
import sys, pandas as pd
rows = []
for run in sys.argv[1:]:
    E = pd.read_json(run + '/equity.jsonl', lines=True)
    t0, t1 = E.t_ms.min(), E.t_ms.max(); mid = (t0 + t1) / 2; hrs = (t1 - t0) / 3.6e6
    for (s, c), g in E.groupby(['strategy', 'coin']):
        g = g.sort_values('t_ms'); a = g[g.t_ms <= mid].equity.iloc[-1] if (g.t_ms <= mid).any() else 0.0
        rows.append(dict(run=run, strategy=s, coin=c, h1=a / (hrs / 2), h2=(g.equity.iloc[-1] - a) / (hrs / 2), all=g.equity.iloc[-1] / hrs))
R = pd.DataFrame(rows)
R.to_csv('/tmp/search/halves.csv', index=False)
P = R.groupby('strategy')[['h1', 'h2', 'all']].sum().round(2)
print(P.sort_values('all', ascending=False).to_string())
