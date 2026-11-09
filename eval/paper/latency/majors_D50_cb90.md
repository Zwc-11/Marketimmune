Segments (hours): f/seg-20261107T2329 2.00, f/seg-20261108T0129 2.00, f/seg-20261108T0329 2.00, f/seg-20261108T0529 2.00, f/seg-20261108T0729 2.00, f/seg-20261108T0929 2.00, f/seg-20261108T1129 2.00, f/seg-20261108T1329 2.00. Latency 25 ms, retimed hl=25,cb=90; fees 1.5 / 4.5 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 1 of 5 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | f/seg-20261107T2329 | f/seg-20261108T0129 | f/seg-20261108T0329 | f/seg-20261108T0529 | f/seg-20261108T0729 | f/seg-20261108T0929 | f/seg-20261108T1129 | f/seg-20261108T1329 |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| hush | `hush@d=3/quiet=5/inf=0.665/tol=0.3` | 250x4 | 0.95 | -1.1 | -1.1 | yes | 0.7 | -4.6 | 0.5 | -2.0 | 2.5 | -6.5 | -0.0 | 0.9 |
| mm | `mm@1.5` | 250x4 | 0.91 | -2.2 | -2.2 | yes | -2.7 | -3.9 | -0.8 | -0.4 | -2.3 | -2.2 | -3.5 | -2.1 |
| zgap | `zgap@0.05` | 250x4 | 0.26 | -3.7 | -3.7 | yes | -6.8 | -7.4 | -3.4 | 0.4 | 1.4 | -2.6 | -1.4 | -9.7 |
| touch | `touch` | 250x4 | 0.13 | -25.5 | -25.5 | yes | -31.0 | -28.7 | -19.0 | -20.5 | -19.4 | -25.9 | -26.1 | -33.8 |

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | f/seg-20261107T2329 | f/seg-20261108T0129 | f/seg-20261108T0329 | f/seg-20261108T0529 | f/seg-20261108T0729 | f/seg-20261108T0929 | f/seg-20261108T1129 | f/seg-20261108T1329 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hush@d=3/quiet=5/inf=0.665/tol=0.3` | 250x4 | 0.95 | -1.1 | 0.7 | -4.6 | 0.5 | -2.0 | 2.5 | -6.5 | -0.0 | 0.9 |
| `mm@1.5` | 250x4 | 0.91 | -2.2 | -2.7 | -3.9 | -0.8 | -0.4 | -2.3 | -2.2 | -3.5 | -2.1 |
| `zgap@0.05` | 250x4 | 0.26 | -3.7 | -6.8 | -7.4 | -3.4 | 0.4 | 1.4 | -2.6 | -1.4 | -9.7 |
| `touch` | 250x4 | 0.13 | -25.5 | -31.0 | -28.7 | -19.0 | -20.5 | -19.4 | -25.9 | -26.1 | -33.8 |

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
| `mm@3` | 250x4 | 2.46 | -0.6 |
