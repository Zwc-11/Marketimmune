Segments (hours): f/seg-20261107T2329 2.00, f/seg-20261108T0129 2.00, f/seg-20261108T0329 2.00, f/seg-20261108T0529 2.00, f/seg-20261108T0729 2.00, f/seg-20261108T0929 2.00, f/seg-20261108T1129 2.00, f/seg-20261108T1329 2.00. Latency 150 ms, retimed hl=150,cb=90; fees 1.5 / 4.5 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 1 of 5 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | f/seg-20261107T2329 | f/seg-20261108T0129 | f/seg-20261108T0329 | f/seg-20261108T0529 | f/seg-20261108T0729 | f/seg-20261108T0929 | f/seg-20261108T1129 | f/seg-20261108T1329 |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| hush | `hush@d=3/quiet=5/inf=0.665/tol=0.3` | 250x4 | 0.64 | -1.7 | -1.7 | yes | 2.7 | -5.9 | 0.8 | -4.6 | 1.9 | -7.5 | -0.6 | -0.2 |
| zgap | `zgap@0.05` | 250x4 | 0.28 | -2.8 | -2.8 | yes | -10.9 | -4.1 | -1.1 | -1.7 | 0.1 | -1.7 | 1.1 | -3.8 |
| mm | `mm@1.5` | 250x4 | 0.72 | -4.3 | -4.3 | yes | -4.1 | -10.1 | -3.0 | -2.7 | -4.8 | -1.1 | -5.5 | -2.8 |
| touch | `touch` | 250x4 | 0.13 | -26.1 | -26.1 | yes | -30.9 | -31.1 | -18.5 | -20.4 | -20.9 | -20.6 | -28.6 | -37.4 |

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | f/seg-20261107T2329 | f/seg-20261108T0129 | f/seg-20261108T0329 | f/seg-20261108T0529 | f/seg-20261108T0729 | f/seg-20261108T0929 | f/seg-20261108T1129 | f/seg-20261108T1329 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hush@d=3/quiet=5/inf=0.665/tol=0.3` | 250x4 | 0.64 | -1.7 | 2.7 | -5.9 | 0.8 | -4.6 | 1.9 | -7.5 | -0.6 | -0.2 |
| `zgap@0.05` | 250x4 | 0.28 | -2.8 | -10.9 | -4.1 | -1.1 | -1.7 | 0.1 | -1.7 | 1.1 | -3.8 |
| `mm@1.5` | 250x4 | 0.72 | -4.3 | -4.1 | -10.1 | -3.0 | -2.7 | -4.8 | -1.1 | -5.5 | -2.8 |
| `touch` | 250x4 | 0.13 | -26.1 | -30.9 | -31.1 | -18.5 | -20.4 | -20.9 | -20.6 | -28.6 | -37.4 |

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
| `mm@3` | 250x4 | 1.54 | -1.3 |
