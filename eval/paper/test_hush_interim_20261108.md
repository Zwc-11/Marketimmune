Segments (hours): test/seg-20261107T2320 0.22, test/seg-20261107T2334 2.00, test/seg-20261108T0134 2.00, test/seg-20261108T0334 0.73. Latency 200 ms; fees 1.5 / 4.5 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 0 of 5 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | test/seg-20261107T2320 | test/seg-20261107T2334 | test/seg-20261108T0134 | test/seg-20261108T0334 |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|
| hush | `hush@d=3/quiet=0/tol=0.3` | 250x4 | 0.36 | -1.7 | -3.0 | no | -1.2 | 1.7 | -5.2 | -2.0 |
| zgap | `zgap@0.05` | 250x4 | 0.30 | -4.5 | -4.5 | yes | -6.8 | -9.4 | -1.8 | 2.4 |

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | test/seg-20261107T2320 | test/seg-20261107T2334 | test/seg-20261108T0134 | test/seg-20261108T0334 |
|---|---|---:|---:|---:|---:|---:|---:|
| `hush@d=3/quiet=0/tol=0.3` | 250x4 | 0.36 | -1.7 | -1.2 | 1.7 | -5.2 | -2.0 |
| `hush@d=3/quiet=5/tol=0.3` | 250x4 | 0.38 | -2.3 | -1.5 | 0.1 | -5.0 | -1.7 |
| `hush@d=4/quiet=5/tol=0.3` | 250x4 | 0.58 | -2.4 | -0.1 | -1.4 | -4.0 | -1.3 |
| `hush@d=3/quiet=5/inf=0.665/tol=0.3` | 250x4 | 0.42 | -2.7 | -0.2 | -0.7 | -5.2 | -1.9 |
| `zgap@0.05` | 250x4 | 0.30 | -4.5 | -6.8 | -9.4 | -1.8 | 2.4 |

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
