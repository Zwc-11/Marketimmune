import pandas as pd, numpy as np
B = pd.read_pickle('/tmp/hip3/bbo.pkl')
def series(c):
    g = B[B.coin == c].sort_values('t')
    s = pd.Series(g.mid.to_numpy(), index=pd.to_datetime(g.t, unit='ms'))
    s = s[~s.index.duplicated(keep='last')]
    return s.resample('250ms').last().ffill()
for a, b in (('io:ANTH', 'xyz:ANT'), ('io:SNDK', 'xyz:SNDK'), ('io:NVDA', 'xyz:NVDA'), ('xyz:SP500', 'xyz:XYZ100'), ('xyz:CL', 'xyz:BRENTOIL'), ('xyz:SKHX', 'xyz:SKHY')):
    x, y = series(a), series(b)
    df = pd.concat([x, y], axis=1, keys=[a, b]).dropna()
    ratio = df[a] / df[b]
    rb = np.log(ratio).diff()
    ra, rb_ = np.log(df[a]).diff(), np.log(df[b]).diff()
    out = []
    for lag in (-8, -4, -2, -1, 0, 1, 2, 4, 8):  # lag>0: a leads b by lag*250ms
        out.append(f'{lag:+d}:{ra.corr(rb_.shift(-lag)):+.2f}')
    print(f'{a} vs {b}: {len(df)} pts, ratio {ratio.mean():.4f} sd {ratio.std()/ratio.mean()*1e4:.1f} bp, corr by lag (250 ms, + = {a} leads):', ' '.join(out))
