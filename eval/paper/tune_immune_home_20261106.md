Segments (hours): night/seg2-20261106T0448 1.18, night/seg3-20261106T0559 1.95, night/seg4-20261106T0757 1.58, live/seg-20261106T1606 2.00, live/seg-20261106T1806 1.48. Held out, not selected on: live/seg-20261106T2003 2.00. Latency 200 ms; fees 1.5 / 4.5 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 3 of 16 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | night/seg2-20261106T0448 | night/seg3-20261106T0559 | night/seg4-20261106T0757 | live/seg-20261106T1606 | live/seg-20261106T1806 | live/seg-20261106T2003 (held out) |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
| guard | `guard@z=0.05/w=1.5/win=5` | 250x4 | 0.61 | 4.3 | 4.3 | yes | 6.7 | 13.5 | 8.8 | -12.6 | 8.1 | 3.8 |
| zgap | `zgap@0.05` | 250x4 | 0.59 | 1.8 | 1.8 | yes | 4.7 | 9.0 | 4.5 | -14.4 | 9.1 | 1.9 |
| immune | `immune@h=30/t=-2` | 250x4 | 0.42 | -11.3 | -11.3 | yes | -0.3 | -13.6 | -7.5 | -31.5 | 6.0 | -4.4 |
| touch | `touch` | 250x4 | 0.10 | -145.6 | -145.6 | yes | -120.7 | -174.7 | -146.1 | -188.0 | -69.3 | -86.6 |

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | night/seg2-20261106T0448 | night/seg3-20261106T0559 | night/seg4-20261106T0757 | live/seg-20261106T1606 | live/seg-20261106T1806 | live/seg-20261106T2003 (held out) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `guard@z=0.05/w=1.5/win=5` | 250x4 | 0.61 | 4.3 | 6.7 | 13.5 | 8.8 | -12.6 | 8.1 | 3.8 |
| `guard@z=0.05/w=1.5/win=5/veto=-5` | 250x4 | 0.61 | 4.3 | 6.7 | 13.5 | 8.8 | -12.6 | 8.1 | 3.8 |
| `guard@z=0.05/w=1.5/win=5/veto=-4` | 250x4 | 0.61 | 4.3 | 6.7 | 13.5 | 8.8 | -12.6 | 8.1 | 3.8 |
| `guard@z=0.05/w=1.5/win=5/veto=-3` | 250x4 | 0.61 | 3.0 | 5.2 | 14.4 | 8.8 | -17.2 | 7.5 | 3.7 |
| `guard@z=0.05/w=1.5/win=5/veto=-2` | 250x4 | 0.62 | 2.5 | 3.0 | 13.1 | 10.7 | -18.4 | 7.8 | 7.2 |
| `guard@z=0.05/veto=-4` | 250x4 | 0.59 | 1.7 | 4.7 | 9.0 | 4.0 | -14.4 | 9.1 | 1.9 |
| `guard@z=0.05/veto=-3` | 250x4 | 0.59 | 1.1 | 5.3 | 9.4 | 4.0 | -16.7 | 7.6 | 1.7 |
| `guard@z=0.05/veto=-2` | 250x4 | 0.60 | 0.6 | 2.0 | 13.1 | 6.5 | -21.7 | 6.7 | 2.9 |
| `zgap@0.05` | 250x4 | 0.59 | 1.8 | 4.7 | 9.0 | 4.5 | -14.4 | 9.1 | 1.9 |
| `immune@h=30/t=-2` | 250x4 | 0.42 | -11.3 | -0.3 | -13.6 | -7.5 | -31.5 | 6.0 | -4.4 |
| `immune@h=10/t=-2` | 250x4 | 0.39 | -12.6 | -6.6 | -7.8 | -8.8 | -34.2 | 1.6 | -8.6 |
| `immune@h=10/t=-3` | 250x4 | 0.17 | -55.7 | -50.1 | -55.8 | -60.3 | -74.8 | -29.0 | -49.0 |
| `touch` | 250x4 | 0.10 | -145.6 | -120.7 | -174.7 | -146.1 | -188.0 | -69.3 | -86.6 |

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
| `immune@h=30/t=-1` | 250x4 | 1.18 | 8.5 |
| `immune@h=10/t=-1` | 250x4 | 1.32 | 3.4 |
| `immune@h=10/t=0` | 250x4 | 2.93 | -2.7 |
