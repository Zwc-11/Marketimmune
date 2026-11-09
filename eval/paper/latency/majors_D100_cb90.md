Segments (hours): f/seg-20261107T2329 2.00, f/seg-20261108T0129 2.00, f/seg-20261108T0329 2.00, f/seg-20261108T0529 2.00, f/seg-20261108T0729 2.00, f/seg-20261108T0929 2.00, f/seg-20261108T1129 2.00, f/seg-20261108T1329 2.00. Latency 50 ms, retimed hl=50,cb=90; fees 1.5 / 4.5 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 1 of 5 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | f/seg-20261107T2329 | f/seg-20261108T0129 | f/seg-20261108T0329 | f/seg-20261108T0529 | f/seg-20261108T0729 | f/seg-20261108T0929 | f/seg-20261108T1129 | f/seg-20261108T1329 |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| hush | `hush@d=3/quiet=5/inf=0.665/tol=0.3` | 250x4 | 0.86 | -0.9 | -0.9 | yes | 1.3 | -4.3 | 0.3 | -2.0 | 3.3 | -7.2 | -0.2 | 1.3 |
| mm | `mm@1.5` | 250x4 | 0.87 | -2.2 | -2.2 | yes | -3.4 | -4.5 | -0.9 | 0.9 | -2.9 | -1.1 | -3.6 | -2.2 |
| zgap | `zgap@0.05` | 250x4 | 0.26 | -4.1 | -4.1 | yes | -9.5 | -6.6 | -3.0 | -0.1 | 0.3 | -3.9 | -1.4 | -8.5 |
| touch | `touch` | 250x4 | 0.13 | -25.7 | -25.7 | yes | -31.2 | -27.6 | -17.7 | -20.6 | -23.2 | -22.1 | -26.3 | -36.9 |

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | f/seg-20261107T2329 | f/seg-20261108T0129 | f/seg-20261108T0329 | f/seg-20261108T0529 | f/seg-20261108T0729 | f/seg-20261108T0929 | f/seg-20261108T1129 | f/seg-20261108T1329 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hush@d=3/quiet=5/inf=0.665/tol=0.3` | 250x4 | 0.86 | -0.9 | 1.3 | -4.3 | 0.3 | -2.0 | 3.3 | -7.2 | -0.2 | 1.3 |
| `mm@1.5` | 250x4 | 0.87 | -2.2 | -3.4 | -4.5 | -0.9 | 0.9 | -2.9 | -1.1 | -3.6 | -2.2 |
| `zgap@0.05` | 250x4 | 0.26 | -4.1 | -9.5 | -6.6 | -3.0 | -0.1 | 0.3 | -3.9 | -1.4 | -8.5 |
| `touch` | 250x4 | 0.13 | -25.7 | -31.2 | -27.6 | -17.7 | -20.6 | -23.2 | -22.1 | -26.3 | -36.9 |

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
| `mm@3` | 250x4 | 2.23 | -1.0 |
