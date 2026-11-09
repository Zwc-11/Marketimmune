Segments (hours): f/seg-20261107T2329 2.00, f/seg-20261108T0129 2.00, f/seg-20261108T0329 2.00, f/seg-20261108T0529 2.00, f/seg-20261108T0729 2.00, f/seg-20261108T0929 2.00, f/seg-20261108T1129 2.00, f/seg-20261108T1329 2.00. Latency 200 ms; fees 1.5 / 4.5 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 1 of 5 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | f/seg-20261107T2329 | f/seg-20261108T0129 | f/seg-20261108T0329 | f/seg-20261108T0529 | f/seg-20261108T0729 | f/seg-20261108T0929 | f/seg-20261108T1129 | f/seg-20261108T1329 |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| hush | `hush@d=3/quiet=5/inf=0.665/tol=0.3` | 250x4 | 0.54 | -1.8 | -1.8 | yes | -0.2 | -4.5 | -0.1 | -2.5 | 1.6 | -5.3 | -0.2 | -3.2 |
| zgap | `zgap@0.05` | 250x4 | 0.29 | -2.2 | -2.2 | yes | -10.8 | -2.4 | -1.5 | -0.0 | -0.5 | 1.4 | 1.2 | -4.5 |
| mm | `mm@1.5` | 250x4 | 0.67 | -4.6 | -4.6 | yes | -4.9 | -10.1 | -2.7 | -0.8 | -4.6 | -2.9 | -6.7 | -4.2 |
| touch | `touch` | 250x4 | 0.12 | -27.1 | -27.1 | yes | -32.8 | -34.7 | -18.1 | -19.0 | -22.0 | -23.6 | -29.8 | -37.1 |

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | f/seg-20261107T2329 | f/seg-20261108T0129 | f/seg-20261108T0329 | f/seg-20261108T0529 | f/seg-20261108T0729 | f/seg-20261108T0929 | f/seg-20261108T1129 | f/seg-20261108T1329 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hush@d=3/quiet=5/inf=0.665/tol=0.3` | 250x4 | 0.54 | -1.8 | -0.2 | -4.5 | -0.1 | -2.5 | 1.6 | -5.3 | -0.2 | -3.2 |
| `zgap@0.05` | 250x4 | 0.29 | -2.2 | -10.8 | -2.4 | -1.5 | -0.0 | -0.5 | 1.4 | 1.2 | -4.5 |
| `mm@1.5` | 250x4 | 0.67 | -4.6 | -4.9 | -10.1 | -2.7 | -0.8 | -4.6 | -2.9 | -6.7 | -4.2 |
| `touch` | 250x4 | 0.12 | -27.1 | -32.8 | -34.7 | -18.1 | -19.0 | -22.0 | -23.6 | -29.8 | -37.1 |

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
| `mm@3` | 250x4 | 1.39 | -1.9 |
