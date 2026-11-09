Segments (hours): f/seg-20261107T2329 2.00, f/seg-20261108T0129 2.00, f/seg-20261108T0329 2.00, f/seg-20261108T0529 2.00, f/seg-20261108T0729 2.00, f/seg-20261108T0929 2.00, f/seg-20261108T1129 2.00, f/seg-20261108T1329 2.00. Latency 265 ms, retimed hl=265,cb=0; fees 1.5 / 4.5 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 1 of 5 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | f/seg-20261107T2329 | f/seg-20261108T0129 | f/seg-20261108T0329 | f/seg-20261108T0529 | f/seg-20261108T0729 | f/seg-20261108T0929 | f/seg-20261108T1129 | f/seg-20261108T1329 |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| hush | `hush@d=3/quiet=5/inf=0.665/tol=0.3` | 250x4 | 0.55 | -1.9 | -1.9 | yes | 0.4 | -5.3 | -0.2 | -1.6 | 1.8 | -5.2 | -1.6 | -3.8 |
| zgap | `zgap@0.05` | 250x4 | 0.29 | -2.4 | -2.4 | yes | -9.7 | -0.0 | -2.2 | -1.2 | 0.5 | -0.9 | 0.2 | -5.7 |
| mm | `mm@1.5` | 250x4 | 0.65 | -4.8 | -4.8 | yes | -4.5 | -9.9 | -3.3 | -0.6 | -5.9 | -2.5 | -8.4 | -3.7 |
| touch | `touch` | 250x4 | 0.13 | -27.0 | -27.0 | yes | -32.5 | -33.3 | -17.9 | -19.6 | -20.7 | -24.1 | -31.9 | -36.3 |

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | f/seg-20261107T2329 | f/seg-20261108T0129 | f/seg-20261108T0329 | f/seg-20261108T0529 | f/seg-20261108T0729 | f/seg-20261108T0929 | f/seg-20261108T1129 | f/seg-20261108T1329 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hush@d=3/quiet=5/inf=0.665/tol=0.3` | 250x4 | 0.55 | -1.9 | 0.4 | -5.3 | -0.2 | -1.6 | 1.8 | -5.2 | -1.6 | -3.8 |
| `zgap@0.05` | 250x4 | 0.29 | -2.4 | -9.7 | -0.0 | -2.2 | -1.2 | 0.5 | -0.9 | 0.2 | -5.7 |
| `mm@1.5` | 250x4 | 0.65 | -4.8 | -4.5 | -9.9 | -3.3 | -0.6 | -5.9 | -2.5 | -8.4 | -3.7 |
| `touch` | 250x4 | 0.13 | -27.0 | -32.5 | -33.3 | -17.9 | -19.6 | -20.7 | -24.1 | -31.9 | -36.3 |

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
| `mm@3` | 250x4 | 1.35 | -2.2 |
