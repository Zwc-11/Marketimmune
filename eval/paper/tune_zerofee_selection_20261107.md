Segments (hours): night/seg2-20261106T0448 1.18, night/seg3-20261106T0559 1.95, night/seg4-20261106T0757 1.58, live/seg-20261106T1606 2.00, live/seg-20261106T1806 1.48, tunedA/seg-20261106T2003 2.00, tunedA/tuned-20261106T2203 2.00, tunedA/tuned-20261107T0003 2.00, tunedA/mm-20261107T0205 1.91, tunedB/seg-20261107T0409 2.00, tunedB/seg-20261107T0609 2.00, tunedB/seg-20261107T0810 2.00, tunedB/seg-20261107T1010 2.00, tunedB/seg-20261107T1210 2.00, tunedB/seg-20261107T1410 1.16, tunedB/seg-20261107T1520 1.67. Latency 400 ms; fees 0 / 0 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 0 of 5 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | night/seg2-20261106T0448 | night/seg3-20261106T0559 | night/seg4-20261106T0757 | live/seg-20261106T1606 | live/seg-20261106T1806 | tunedA/seg-20261106T2003 | tunedA/tuned-20261106T2203 | tunedA/tuned-20261107T0003 | tunedA/mm-20261107T0205 | tunedB/seg-20261107T0409 | tunedB/seg-20261107T0609 | tunedB/seg-20261107T0810 | tunedB/seg-20261107T1010 | tunedB/seg-20261107T1210 | tunedB/seg-20261107T1410 | tunedB/seg-20261107T1520 |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| zgap | `zgap@0.05` | 250x4 | 0.31 | 1.0 | 1.0 | yes | 9.9 | 5.2 | 11.7 | -13.6 | 9.8 | -6.1 | 2.7 | 2.0 | 5.5 | -1.9 | -2.8 | 2.5 | 1.1 | -5.3 | -1.8 | 4.7 |
| gap | `gap@0.1` | 250x4 | 0.40 | -0.2 | -0.2 | yes | 9.7 | -0.7 | 11.6 | -19.0 | 4.8 | -3.5 | 1.1 | 3.3 | 1.1 | -0.7 | -2.0 | 2.6 | -0.1 | -5.9 | -0.0 | 3.5 |
| disloc | `disloc@d=2/tol=0.3/hold=120/stop=20` | 250x4 | 0.31 | -6.3 | -6.3 | yes | -4.5 | -20.2 | -6.9 | -28.9 | 1.6 | -5.2 | -2.5 | -2.2 | -12.9 | 0.8 | -3.1 | -5.0 | -3.8 | -0.3 | -4.0 | 0.8 |
| lead | `lead@h0=1/skew=0.5/tol=0.3` | 250x4 | 0.38 | -7.9 | -7.9 | yes | -0.3 | -45.9 | -16.1 | -25.2 | 5.9 | -10.0 | -0.4 | -0.6 | -10.9 | -0.2 | -1.8 | -5.3 | -1.9 | -1.6 | -6.6 | -0.0 |
| immune | `immune@h=30/t=-1/fee=0` | 250x4 | 0.16 | -10.6 | -10.6 | yes | -10.1 | -26.8 | -27.3 | -44.9 | -3.8 | -14.3 | -3.1 | 2.0 | -4.0 | -6.6 | -13.8 | -3.1 | -1.7 | -7.0 | -9.3 | 5.9 |

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | night/seg2-20261106T0448 | night/seg3-20261106T0559 | night/seg4-20261106T0757 | live/seg-20261106T1606 | live/seg-20261106T1806 | tunedA/seg-20261106T2003 | tunedA/tuned-20261106T2203 | tunedA/tuned-20261107T0003 | tunedA/mm-20261107T0205 | tunedB/seg-20261107T0409 | tunedB/seg-20261107T0609 | tunedB/seg-20261107T0810 | tunedB/seg-20261107T1010 | tunedB/seg-20261107T1210 | tunedB/seg-20261107T1410 | tunedB/seg-20261107T1520 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `zgap@0.05` | 250x4 | 0.31 | 1.0 | 9.9 | 5.2 | 11.7 | -13.6 | 9.8 | -6.1 | 2.7 | 2.0 | 5.5 | -1.9 | -2.8 | 2.5 | 1.1 | -5.3 | -1.8 | 4.7 |
| `gap@0.1` | 250x4 | 0.40 | -0.2 | 9.7 | -0.7 | 11.6 | -19.0 | 4.8 | -3.5 | 1.1 | 3.3 | 1.1 | -0.7 | -2.0 | 2.6 | -0.1 | -5.9 | -0.0 | 3.5 |
| `disloc@d=2/tol=0.3/hold=120/stop=20` | 250x4 | 0.31 | -6.3 | -4.5 | -20.2 | -6.9 | -28.9 | 1.6 | -5.2 | -2.5 | -2.2 | -12.9 | 0.8 | -3.1 | -5.0 | -3.8 | -0.3 | -4.0 | 0.8 |
| `lead@h0=1/skew=0.5/tol=0.3` | 250x4 | 0.38 | -7.9 | -0.3 | -45.9 | -16.1 | -25.2 | 5.9 | -10.0 | -0.4 | -0.6 | -10.9 | -0.2 | -1.8 | -5.3 | -1.9 | -1.6 | -6.6 | -0.0 |
| `immune@h=30/t=-1/fee=0` | 250x4 | 0.16 | -10.6 | -10.1 | -26.8 | -27.3 | -44.9 | -3.8 | -14.3 | -3.1 | 2.0 | -4.0 | -6.6 | -13.8 | -3.1 | -1.7 | -7.0 | -9.3 | 5.9 |

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
