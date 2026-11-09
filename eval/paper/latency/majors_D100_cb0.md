Segments (hours): f/seg-20261107T2329 2.00, f/seg-20261108T0129 2.00, f/seg-20261108T0329 2.00, f/seg-20261108T0529 2.00, f/seg-20261108T0729 2.00, f/seg-20261108T0929 2.00, f/seg-20261108T1129 2.00, f/seg-20261108T1329 2.00. Latency 50 ms, retimed hl=50,cb=0; fees 1.5 / 4.5 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 1 of 5 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | f/seg-20261107T2329 | f/seg-20261108T0129 | f/seg-20261108T0329 | f/seg-20261108T0529 | f/seg-20261108T0729 | f/seg-20261108T0929 | f/seg-20261108T1129 | f/seg-20261108T1329 |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| hush | `hush@d=3/quiet=5/inf=0.665/tol=0.3` | 250x4 | 0.84 | -0.9 | -0.9 | yes | 1.8 | -4.5 | 0.7 | -2.0 | 2.4 | -7.2 | 0.4 | 1.3 |
| mm | `mm@1.5` | 250x4 | 0.89 | -2.3 | -2.3 | yes | -3.3 | -4.3 | -1.1 | 0.5 | -2.8 | -1.2 | -4.6 | -1.6 |
| zgap | `zgap@0.05` | 250x4 | 0.27 | -3.2 | -3.2 | yes | -8.7 | -5.4 | -3.1 | 1.0 | 0.1 | -1.0 | 1.3 | -10.0 |
| touch | `touch` | 250x4 | 0.13 | -25.2 | -25.2 | yes | -32.0 | -28.5 | -17.0 | -19.6 | -21.6 | -21.9 | -25.2 | -35.9 |

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | f/seg-20261107T2329 | f/seg-20261108T0129 | f/seg-20261108T0329 | f/seg-20261108T0529 | f/seg-20261108T0729 | f/seg-20261108T0929 | f/seg-20261108T1129 | f/seg-20261108T1329 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hush@d=3/quiet=5/inf=0.665/tol=0.3` | 250x4 | 0.84 | -0.9 | 1.8 | -4.5 | 0.7 | -2.0 | 2.4 | -7.2 | 0.4 | 1.3 |
| `mm@1.5` | 250x4 | 0.89 | -2.3 | -3.3 | -4.3 | -1.1 | 0.5 | -2.8 | -1.2 | -4.6 | -1.6 |
| `zgap@0.05` | 250x4 | 0.27 | -3.2 | -8.7 | -5.4 | -3.1 | 1.0 | 0.1 | -1.0 | 1.3 | -10.0 |
| `touch` | 250x4 | 0.13 | -25.2 | -32.0 | -28.5 | -17.0 | -19.6 | -21.6 | -21.9 | -25.2 | -35.9 |

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
| `mm@3` | 250x4 | 2.30 | -0.6 |
