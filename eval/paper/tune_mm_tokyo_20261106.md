Segments (hours): night/seg2-20261106T0448 1.19, night/seg3-20261106T0559 1.95, night/seg4-20261106T0757 1.58, live/seg-20261106T1606 2.00, live/seg-20261106T1806 1.48. Held out, not selected on: live/seg-20261106T2003 0.95. Latency 20 ms, retimed hl=50,cb=70; fees 1.5 / 4.5 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 5 of 11 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | night/seg2-20261106T0448 | night/seg3-20261106T0559 | night/seg4-20261106T0757 | live/seg-20261106T1606 | live/seg-20261106T1806 | live/seg-20261106T2003 (held out) |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
| zgap | `zgap@0.05` | 250x4 | 0.43 | 4.3 | 4.3 | yes | 6.0 | 10.1 | 6.0 | -6.5 | 8.2 | 10.6 |
| improve+gap | `improve+gap@0.05` | 250x4 | 0.43 | 3.5 | 3.5 | yes | 6.1 | 11.2 | 6.5 | -10.0 | 6.6 | 10.0 |
| mm | `mm@1` | 250x4 | 0.87 | -11.6 | -11.6 | yes | -7.7 | -16.2 | -18.5 | -10.8 | -2.5 | -16.0 |
| touch | `touch` | 250x4 | 0.11 | -125.7 | -125.7 | yes | -111.0 | -143.0 | -131.1 | -158.1 | -65.4 | -78.1 |

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | night/seg2-20261106T0448 | night/seg3-20261106T0559 | night/seg4-20261106T0757 | live/seg-20261106T1606 | live/seg-20261106T1806 | live/seg-20261106T2003 (held out) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `zgap@0.05` | 250x4 | 0.43 | 4.3 | 6.0 | 10.1 | 6.0 | -6.5 | 8.2 | 10.6 |
| `improve+gap@0.05` | 250x4 | 0.43 | 3.5 | 6.1 | 11.2 | 6.5 | -10.0 | 6.6 | 10.0 |
| `mm@1` | 250x4 | 0.87 | -11.6 | -7.7 | -16.2 | -18.5 | -10.8 | -2.5 | -16.0 |
| `mm@0.5` | 250x4 | 0.45 | -27.2 | -20.4 | -35.1 | -31.7 | -33.4 | -8.9 | -25.3 |
| `mm@0` | 250x4 | 0.21 | -52.1 | -43.8 | -53.8 | -59.3 | -62.8 | -34.3 | -52.3 |
| `touch` | 250x4 | 0.11 | -125.7 | -111.0 | -143.0 | -131.1 | -158.1 | -65.4 | -78.1 |

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
| `mm@3` | 250x4 | 2.91 | -0.8 |
| `mm@5` | 250x4 | 6.70 | -1.0 |
| `mm@2` | 250x4 | 1.64 | -2.3 |
| `mm@1.5` | 250x4 | 1.27 | -6.0 |
| `mm@h=2/skew=6` | 250x4 | 1.22 | -6.1 |
