Segments (hours): fresh/seg-20261107T0409 2.00, fresh/seg-20261107T0609 2.00, fresh/seg-20261107T0810 2.00, fresh/seg-20261107T1010 2.00, fresh/seg-20261107T1210 2.00, fresh/seg-20261107T1410 1.16, fresh/seg-20261107T1520 1.67. Latency 200 ms; fees 1.5 / 4.5 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 0 of 3 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | fresh/seg-20261107T0409 | fresh/seg-20261107T0609 | fresh/seg-20261107T0810 | fresh/seg-20261107T1010 | fresh/seg-20261107T1210 | fresh/seg-20261107T1410 | fresh/seg-20261107T1520 |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| immune | `immune@h=30/t=-1` | 250x4 | 0.65 | -1.3 | -1.3 | yes | -4.5 | -5.5 | 3.2 | 2.2 | -7.9 | 2.1 | 3.2 |
| zgap | `zgap@0.05` | 250x4 | 0.27 | -4.9 | -4.9 | yes | -10.1 | -3.8 | -2.6 | -1.1 | -8.4 | -5.0 | -2.7 |
| touch | `touch` | 250x4 | 0.11 | -34.5 | -34.5 | yes | -27.7 | -28.0 | -33.9 | -34.2 | -35.5 | -38.8 | -46.9 |

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | fresh/seg-20261107T0409 | fresh/seg-20261107T0609 | fresh/seg-20261107T0810 | fresh/seg-20261107T1010 | fresh/seg-20261107T1210 | fresh/seg-20261107T1410 | fresh/seg-20261107T1520 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `immune@h=30/t=-1` | 250x4 | 0.65 | -1.3 | -4.5 | -5.5 | 3.2 | 2.2 | -7.9 | 2.1 | 3.2 |
| `zgap@0.05` | 250x4 | 0.27 | -4.9 | -10.1 | -3.8 | -2.6 | -1.1 | -8.4 | -5.0 | -2.7 |
| `touch` | 250x4 | 0.11 | -34.5 | -27.7 | -28.0 | -33.9 | -34.2 | -35.5 | -38.8 | -46.9 |

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
