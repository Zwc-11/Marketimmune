import gzip, glob, json, sys
import numpy as np, pandas as pd
rows = []
for f in sorted(glob.glob('/tmp/hip3/raw/hl-*.log.gz')):
    try:
        for line in gzip.open(f, 'rt'):
            ns, raw = line.split('\t', 1)
            if '"activeAssetCtx"' not in raw[:40]: continue
            try: m = json.loads(raw)
            except ValueError: continue
            d = m['data']; c = d['ctx']
            rows.append((d['coin'], int(ns) // 1_000_000, float(c['oraclePx']), float(c['markPx']), float(c.get('midPx') or 'nan'), float(c['funding'])))
    except EOFError: pass
O = pd.DataFrame(rows, columns=['coin', 't', 'oracle', 'mark', 'mid', 'funding'])
out = []
for coin, g in O.groupby('coin'):
    g = g.sort_values('t')
    ch = g.oracle.diff().ne(0)
    upd = g.t[ch].diff().median() / 1000
    gap = (g.mid - g.oracle) / g.oracle * 1e4
    out.append({'coin': coin, 'msgs': len(g), 'oracle_changes': int(ch.sum()), 'median_s_between_oracle_changes': upd,
                'gap_mean_bp': gap.mean(), 'gap_sd_bp': gap.std(), 'oracle_range_bp': (g.oracle.max() / g.oracle.min() - 1) * 1e4,
                'mid_range_bp': (g.mid.max() / g.mid.min() - 1) * 1e4, 'funding_8h_bp': g.funding.iloc[-1] * 8 * 1e4})
print(pd.DataFrame(out).sort_values('msgs', ascending=False).round(2).to_string(index=False))
