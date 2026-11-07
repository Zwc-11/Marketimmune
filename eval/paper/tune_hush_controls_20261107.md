Segments (hours): night/seg2-20261106T0448 1.18, night/seg3-20261106T0559 1.95, night/seg4-20261106T0757 1.58, live/seg-20261106T1606 2.00, live/seg-20261106T1806 1.48, tuned/seg-20261106T2003 2.00, tuned/tuned-20261106T2203 2.00, tuned/tuned-20261107T0003 2.00, tuned/mm-20261107T0205 1.91, tuned/seg-20261107T0409 2.00, tuned/seg-20261107T0609 2.00, tuned/seg-20261107T0810 2.00, tuned/seg-20261107T1010 2.00, tuned/seg-20261107T1210 2.00, tuned/seg-20261107T1410 1.16, tuned/seg-20261107T1520 2.00, tuned/seg-20261107T1720 2.00, tuned/seg-20261107T1920 0.66. Latency 200 ms; fees 1.5 / 4.5 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 3 of 8 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | night/seg2-20261106T0448 | night/seg3-20261106T0559 | night/seg4-20261106T0757 | live/seg-20261106T1606 | live/seg-20261106T1806 | tuned/seg-20261106T2003 | tuned/tuned-20261106T2203 | tuned/tuned-20261107T0003 | tuned/mm-20261107T0205 | tuned/seg-20261107T0409 | tuned/seg-20261107T0609 | tuned/seg-20261107T0810 | tuned/seg-20261107T1010 | tuned/seg-20261107T1210 | tuned/seg-20261107T1410 | tuned/seg-20261107T1520 | tuned/seg-20261107T1720 | tuned/seg-20261107T1920 |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| hush | `hush@d=3/quiet=5/inf=0.665/tol=0.3` | 250x4 | 0.62 | 2.3 | 2.3 | yes | -1.2 | 7.6 | 6.4 | 12.6 | 7.1 | 10.7 | -6.2 | -0.1 | -3.9 | 0.1 | 1.9 | -0.4 | 3.3 | 2.3 | -3.9 | 2.1 | -0.3 | -1.7 |

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | night/seg2-20261106T0448 | night/seg3-20261106T0559 | night/seg4-20261106T0757 | live/seg-20261106T1606 | live/seg-20261106T1806 | tuned/seg-20261106T2003 | tuned/tuned-20261106T2203 | tuned/tuned-20261107T0003 | tuned/mm-20261107T0205 | tuned/seg-20261107T0409 | tuned/seg-20261107T0609 | tuned/seg-20261107T0810 | tuned/seg-20261107T1010 | tuned/seg-20261107T1210 | tuned/seg-20261107T1410 | tuned/seg-20261107T1520 | tuned/seg-20261107T1720 | tuned/seg-20261107T1920 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hush@d=3/quiet=5/inf=0.665/tol=0.3` | 250x4 | 0.62 | 2.3 | -1.2 | 7.6 | 6.4 | 12.6 | 7.1 | 10.7 | -6.2 | -0.1 | -3.9 | 0.1 | 1.9 | -0.4 | 3.3 | 2.3 | -3.9 | 2.1 | -0.3 | -1.7 |
| `hush@d=3/quiet=30/tol=0.3` | 250x4 | 0.57 | 1.6 | -2.2 | 8.9 | 18.6 | 4.1 | 7.0 | 10.8 | -7.8 | -1.2 | -5.8 | -1.9 | -1.4 | -4.7 | 3.2 | 2.9 | -0.3 | 1.2 | -0.1 | -1.5 |
| `hush@d=4/quiet=5/tol=0.3` | 250x4 | 0.79 | 1.6 | -3.0 | 7.2 | 5.0 | 6.5 | 3.3 | 9.8 | -1.9 | -2.2 | -11.2 | 2.8 | 0.6 | -1.3 | 3.6 | 4.7 | -4.6 | 5.1 | -0.4 | -1.4 |
| `hush@d=3/quiet=5/tol=0.3` | 250x4 | 0.53 | 1.1 | -6.4 | 5.2 | 7.4 | 11.2 | 4.9 | 7.2 | -6.7 | -1.1 | -9.1 | 0.6 | 0.2 | -1.1 | 3.4 | 3.2 | -2.1 | 0.5 | -0.7 | -1.6 |
| `hush@d=3/quiet=0/tol=0.3` | 250x4 | 0.46 | -2.6 | -8.6 | -24.5 | -1.9 | 5.3 | 3.8 | 8.5 | -6.4 | -1.6 | -11.0 | -2.0 | -1.0 | -3.1 | 2.6 | -1.3 | -2.5 | -1.8 | -0.1 | -1.6 |

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
| `hush@d=3/quiet=5/z=0.05/tol=1` | 250x4 | 4.18 | 2.2 |
| `hush@d=3/quiet=0/z=0.05/tol=1` | 250x4 | 3.89 | 2.2 |
| `hush@d=5/quiet=5/tol=0.3` | 250x4 | 1.11 | 2.0 |
