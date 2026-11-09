Segments (hours): f/seg-20261107T2329 2.00, f/seg-20261108T0129 2.00, f/seg-20261108T0329 2.00, f/seg-20261108T0529 2.00, f/seg-20261108T0729 2.00, f/seg-20261108T0929 2.00, f/seg-20261108T1129 2.00, f/seg-20261108T1329 2.00. Latency 100 ms, retimed hl=100,cb=90; fees 1.5 / 4.5 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 1 of 5 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | f/seg-20261107T2329 | f/seg-20261108T0129 | f/seg-20261108T0329 | f/seg-20261108T0529 | f/seg-20261108T0729 | f/seg-20261108T0929 | f/seg-20261108T1129 | f/seg-20261108T1329 |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| hush | `hush@d=3/quiet=5/inf=0.665/tol=0.3` | 250x4 | 0.74 | -1.3 | -1.3 | yes | 1.2 | -3.5 | 0.4 | -3.0 | 1.2 | -7.8 | 0.7 | -0.1 |
| mm | `mm@1.5` | 250x4 | 0.81 | -3.0 | -3.0 | yes | -4.1 | -5.2 | -2.5 | -1.0 | -3.4 | -1.5 | -3.8 | -2.6 |
| zgap | `zgap@0.05` | 250x4 | 0.27 | -4.1 | -4.1 | yes | -9.6 | -6.1 | -3.8 | -1.4 | 0.6 | -2.8 | -1.2 | -8.4 |
| touch | `touch` | 250x4 | 0.13 | -26.1 | -26.1 | yes | -32.6 | -29.0 | -19.4 | -21.0 | -19.4 | -23.9 | -26.4 | -36.8 |

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | f/seg-20261107T2329 | f/seg-20261108T0129 | f/seg-20261108T0329 | f/seg-20261108T0529 | f/seg-20261108T0729 | f/seg-20261108T0929 | f/seg-20261108T1129 | f/seg-20261108T1329 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hush@d=3/quiet=5/inf=0.665/tol=0.3` | 250x4 | 0.74 | -1.3 | 1.2 | -3.5 | 0.4 | -3.0 | 1.2 | -7.8 | 0.7 | -0.1 |
| `mm@1.5` | 250x4 | 0.81 | -3.0 | -4.1 | -5.2 | -2.5 | -1.0 | -3.4 | -1.5 | -3.8 | -2.6 |
| `zgap@0.05` | 250x4 | 0.27 | -4.1 | -9.6 | -6.1 | -3.8 | -1.4 | 0.6 | -2.8 | -1.2 | -8.4 |
| `touch` | 250x4 | 0.13 | -26.1 | -32.6 | -29.0 | -19.4 | -21.0 | -19.4 | -23.9 | -26.4 | -36.8 |

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
| `mm@3` | 250x4 | 1.79 | -1.2 |
