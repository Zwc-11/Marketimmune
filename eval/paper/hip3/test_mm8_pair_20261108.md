Segments (hours): test/test 6.00. Latency 200 ms; fees 0.3 / 0.9 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 0 of 4 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | test/test |
|---|---|---|---:|---:|---:|---|---:|
| mm | `mm@10` | 250x4 | 0.16 | 0.9 | 0.5 | yes | 0.9 |
| touch | `touch` | 250x4 | 0.04 | -42.7 | -42.7 | yes | -42.7 |

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | test/test |
|---|---|---:|---:|---:|
| `mm@10` | 250x4 | 0.16 | 0.9 | 0.9 |
| `mm@8` | 250x4 | 0.13 | 0.5 | 0.5 |
| `mm@6` | 250x4 | 0.13 | -2.8 | -2.8 |
| `touch` | 250x4 | 0.04 | -42.7 | -42.7 |

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
