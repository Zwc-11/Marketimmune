Segments (hours): night/seg2-20261106T0448 1.19, night/seg3-20261106T0559 1.95, night/seg4-20261106T0757 1.58, live/seg-20261106T1606 2.00, live/seg-20261106T1806 1.48. Held out, not selected on: live/seg-20261106T2003 0.95. Latency 20 ms, retimed hl=50,cb=70; fees -0.3 / 4.5 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 5 of 11 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | night/seg2-20261106T0448 | night/seg3-20261106T0559 | night/seg4-20261106T0757 | live/seg-20261106T1606 | live/seg-20261106T1806 | live/seg-20261106T2003 (held out) |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
| zgap | `zgap@0.05` | 250x4 | 0.43 | 17.8 | 17.8 | yes | 19.3 | 23.9 | 20.2 | 10.6 | 15.7 | 20.4 |
| improve+gap | `improve+gap@0.05` | 250x4 | 0.43 | 17.0 | 17.0 | yes | 19.2 | 24.9 | 20.5 | 7.6 | 13.9 | 19.8 |
| mm | `mm@1` | 250x4 | 0.87 | 2.6 | 2.6 | yes | 3.0 | 0.1 | -2.3 | 7.2 | 4.5 | -3.2 |
| touch | `touch` | 250x4 | 0.11 | -43.7 | -43.7 | yes | -38.8 | -61.4 | -54.3 | -47.7 | -7.3 | -15.7 |

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | night/seg2-20261106T0448 | night/seg3-20261106T0559 | night/seg4-20261106T0757 | live/seg-20261106T1606 | live/seg-20261106T1806 | live/seg-20261106T2003 (held out) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `zgap@0.05` | 250x4 | 0.43 | 17.8 | 19.3 | 23.9 | 20.2 | 10.6 | 15.7 | 20.4 |
| `improve+gap@0.05` | 250x4 | 0.43 | 17.0 | 19.2 | 24.9 | 20.5 | 7.6 | 13.9 | 19.8 |
| `mm@1` | 250x4 | 0.87 | 2.6 | 3.0 | 0.1 | -2.3 | 7.2 | 4.5 | -3.2 |
| `mm@0.5` | 250x4 | 0.46 | 0.1 | 1.5 | -8.0 | 0.3 | 1.5 | 7.5 | -0.8 |
| `mm@0` | 250x4 | 0.21 | -5.3 | -0.3 | -12.1 | -8.9 | -2.8 | -0.1 | -7.5 |
| `touch` | 250x4 | 0.11 | -43.7 | -38.8 | -61.4 | -54.3 | -47.7 | -7.3 | -15.7 |

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
| `mm@2` | 250x4 | 1.64 | 2.8 |
| `mm@1.5` | 250x4 | 1.27 | 2.1 |
| `mm@3` | 250x4 | 2.91 | 1.3 |
| `mm@h=2/skew=6` | 250x4 | 1.22 | 1.1 |
| `mm@5` | 250x4 | 6.70 | -0.5 |
