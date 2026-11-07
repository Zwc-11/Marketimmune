Segments (hours): fresh/mm-20261107T1700 0.33, fresh/seg-20261107T1720 2.00, fresh/seg-20261107T1920 0.66. Latency 200 ms; fees 1.5 / 4.5 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 1 of 4 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | fresh/mm-20261107T1700 | fresh/seg-20261107T1720 | fresh/seg-20261107T1920 |
|---|---|---|---:|---:|---:|---|---:|---:|---:|
| sweep | `sweep@move=5/win=3/wait=5/hold=60/stop=20` | 250x4 | 0.14 | -0.4 | -0.4 | yes | -1.5 | -0.3 | -0.0 |
| disloc | `disloc@d=3/x=1/tol=0.3/hold=120/stop=20` | 250x4 | 0.66 | -2.1 | -2.1 | yes | -3.2 | -2.1 | -1.5 |
| zgap | `zgap@0.05` | 250x4 | 0.25 | -4.8 | -4.8 | yes | -12.3 | -5.3 | 0.6 |

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | fresh/mm-20261107T1700 | fresh/seg-20261107T1720 | fresh/seg-20261107T1920 |
|---|---|---:|---:|---:|---:|---:|
| `sweep@move=5/win=3/wait=5/hold=60/stop=20` | 250x4 | 0.14 | -0.4 | -1.5 | -0.3 | -0.0 |
| `disloc@d=3/x=1/tol=0.3/hold=120/stop=20` | 250x4 | 0.66 | -2.1 | -3.2 | -2.1 | -1.5 |
| `zgap@0.05` | 250x4 | 0.25 | -4.8 | -12.3 | -5.3 | 0.6 |

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
| `lead@h0=2/skew=0.5/tol=0.3` | 250x4 | 1.04 | -1.2 |
