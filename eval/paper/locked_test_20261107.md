Segments (hours): live/tuned-20261106T2203 2.00, live/tuned-20261107T0003 2.00, live/mm-20261107T0205 1.91. Latency 200 ms; fees 1.5 / 4.5 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 1 of 8 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | live/tuned-20261106T2203 | live/tuned-20261107T0003 | live/mm-20261107T0205 |
|---|---|---|---:|---:|---:|---|---:|---:|---:|
| immune | `immune@h=30/t=-1` | 250x4 | 0.61 | 2.4 | 2.4 | yes | 5.7 | 2.0 | -0.7 |
| guard | `guard@z=0.05/w=1.5/win=5/veto=-2` | 250x4 | 0.27 | -0.1 | -0.1 | yes | 1.0 | -1.4 | 0.1 |
| optimal | `optimal@phi=0` | 250x4 | 0.48 | -0.4 | -0.4 | yes | -3.4 | 0.3 | 2.0 |
| zgap | `zgap@0.05` | 250x4 | 0.26 | -1.2 | -1.2 | yes | -0.5 | -4.4 | 1.4 |
| mm | `mm@h=2/skew=6` | 250x4 | 0.51 | -7.0 | -7.0 | yes | -6.1 | -4.8 | -10.4 |
| touch | `touch` | 250x4 | 0.09 | -46.9 | -46.9 | yes | -46.1 | -34.9 | -60.3 |

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | live/tuned-20261106T2203 | live/tuned-20261107T0003 | live/mm-20261107T0205 |
|---|---|---:|---:|---:|---:|---:|
| `immune@h=30/t=-1` | 250x4 | 0.61 | 2.4 | 5.7 | 2.0 | -0.7 |
| `guard@z=0.05/w=1.5/win=5/veto=-2` | 250x4 | 0.27 | -0.1 | 1.0 | -1.4 | 0.1 |
| `guard@z=0.05/w=1.5/win=5` | 250x4 | 0.28 | -1.7 | -0.9 | -3.9 | -0.4 |
| `optimal@phi=0` | 250x4 | 0.48 | -0.4 | -3.4 | 0.3 | 2.0 |
| `zgap@0.05` | 250x4 | 0.26 | -1.2 | -0.5 | -4.4 | 1.4 |
| `mm@h=2/skew=6` | 250x4 | 0.51 | -7.0 | -6.1 | -4.8 | -10.4 |
| `touch` | 250x4 | 0.09 | -46.9 | -46.1 | -34.9 | -60.3 |

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
| `optimal@phi=0.01` | 250x4 | inf | 0.0 |
