Segments (hours): m/seg-20261107T2329 2.00, m/seg-20261108T0129 2.00, m/seg-20261108T0329 2.00, m/seg-20261108T0529 2.00, m/seg-20261108T0729 2.00, m/seg-20261108T0929 2.00, m/seg-20261108T1129 2.00, m/seg-20261108T1329 2.00. Latency 200 ms; fees 1.5 / 4.5 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 4 of 4 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | m/seg-20261107T2329 | m/seg-20261108T0129 | m/seg-20261108T0329 | m/seg-20261108T0529 | m/seg-20261108T0729 | m/seg-20261108T0929 | m/seg-20261108T1129 | m/seg-20261108T1329 |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | m/seg-20261107T2329 | m/seg-20261108T0129 | m/seg-20261108T0329 | m/seg-20261108T0529 | m/seg-20261108T0729 | m/seg-20261108T0929 | m/seg-20261108T1129 | m/seg-20261108T1329 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
| `hush@d=6/quiet=0/tol=0.3` | 250x4 | 1.10 | 0.9 |
| `hush@d=8/quiet=0/tol=0.3` | 250x4 | 1.90 | 0.6 |
| `hush@d=10/quiet=0/tol=0.3` | 250x4 | 2.07 | 0.6 |
| `hush@d=12/quiet=0/tol=0.3` | 250x4 | 2.44 | 0.6 |
