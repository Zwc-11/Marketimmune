Segments (hours): fresh/mm-20261107T1700 0.33, fresh/seg-20261107T1720 2.00, fresh/seg-20261107T1920 0.66. Latency 400 ms; fees 0 / 0 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 0 of 1 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | fresh/mm-20261107T1700 | fresh/seg-20261107T1720 | fresh/seg-20261107T1920 |
|---|---|---|---:|---:|---:|---|---:|---:|---:|
| zgap | `zgap@0.05` | 250x4 | 0.22 | -0.3 | -0.3 | yes | -8.8 | -0.2 | 3.9 |

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | fresh/mm-20261107T1700 | fresh/seg-20261107T1720 | fresh/seg-20261107T1920 |
|---|---|---:|---:|---:|---:|---:|
| `zgap@0.05` | 250x4 | 0.22 | -0.3 | -8.8 | -0.2 | 3.9 |

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
