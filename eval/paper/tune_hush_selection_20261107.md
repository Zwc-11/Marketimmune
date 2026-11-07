Segments (hours): night/seg2-20261106T0448 1.18, night/seg3-20261106T0559 1.95, night/seg4-20261106T0757 1.58, live/seg-20261106T1606 2.00, live/seg-20261106T1806 1.48, tuned/seg-20261106T2003 2.00, tuned/tuned-20261106T2203 2.00, tuned/tuned-20261107T0003 2.00, tuned/mm-20261107T0205 1.91, tuned/seg-20261107T0409 2.00, tuned/seg-20261107T0609 2.00, tuned/seg-20261107T0810 2.00, tuned/seg-20261107T1010 2.00, tuned/seg-20261107T1210 2.00, tuned/seg-20261107T1410 1.16, tuned/seg-20261107T1520 2.00, tuned/seg-20261107T1720 2.00, tuned/seg-20261107T1920 0.66. Latency 200 ms; fees 1.5 / 4.5 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 1 of 6 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | night/seg2-20261106T0448 | night/seg3-20261106T0559 | night/seg4-20261106T0757 | live/seg-20261106T1606 | live/seg-20261106T1806 | tuned/seg-20261106T2003 | tuned/tuned-20261106T2203 | tuned/tuned-20261107T0003 | tuned/mm-20261107T0205 | tuned/seg-20261107T0409 | tuned/seg-20261107T0609 | tuned/seg-20261107T0810 | tuned/seg-20261107T1010 | tuned/seg-20261107T1210 | tuned/seg-20261107T1410 | tuned/seg-20261107T1520 | tuned/seg-20261107T1720 | tuned/seg-20261107T1920 |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| hush | `hush@d=3/quiet=5/tol=0.3` | 250x4 | 0.53 | 1.1 | 1.1 | yes | -6.4 | 5.2 | 7.4 | 11.2 | 4.9 | 7.2 | -6.7 | -1.1 | -9.1 | 0.6 | 0.2 | -1.1 | 3.4 | 3.2 | -2.1 | 0.5 | -0.7 | -1.6 |
| zgap | `zgap@0.05` | 250x4 | 0.38 | -2.7 | -2.7 | yes | 4.7 | 9.0 | 4.5 | -14.4 | 9.1 | -7.0 | -0.5 | -4.4 | 1.4 | -10.1 | -3.8 | -2.6 | -1.1 | -8.4 | -5.0 | -6.0 | -5.3 | 0.6 |

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | night/seg2-20261106T0448 | night/seg3-20261106T0559 | night/seg4-20261106T0757 | live/seg-20261106T1606 | live/seg-20261106T1806 | tuned/seg-20261106T2003 | tuned/tuned-20261106T2203 | tuned/tuned-20261107T0003 | tuned/mm-20261107T0205 | tuned/seg-20261107T0409 | tuned/seg-20261107T0609 | tuned/seg-20261107T0810 | tuned/seg-20261107T1010 | tuned/seg-20261107T1210 | tuned/seg-20261107T1410 | tuned/seg-20261107T1520 | tuned/seg-20261107T1720 | tuned/seg-20261107T1920 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hush@d=3/quiet=5/tol=0.3` | 250x4 | 0.53 | 1.1 | -6.4 | 5.2 | 7.4 | 11.2 | 4.9 | 7.2 | -6.7 | -1.1 | -9.1 | 0.6 | 0.2 | -1.1 | 3.4 | 3.2 | -2.1 | 0.5 | -0.7 | -1.6 |
| `hush@d=2/quiet=30/tol=0.3` | 250x4 | 0.38 | -3.0 | -12.1 | -12.1 | 11.8 | -4.3 | -0.2 | 4.4 | -10.2 | -2.4 | -4.4 | -4.1 | -5.9 | -1.4 | -1.2 | -2.6 | 1.3 | -3.2 | -2.1 | -2.6 |
| `hush@d=2/quiet=5/tol=0.3` | 250x4 | 0.34 | -5.2 | -8.7 | -27.0 | -11.8 | -2.1 | -1.3 | -3.5 | -8.4 | -1.6 | -4.5 | -2.3 | -4.0 | -1.8 | -2.0 | -4.0 | -3.9 | -1.6 | -3.1 | -2.6 |
| `hush@d=1/quiet=5/tol=0.3` | 250x4 | 0.19 | -18.7 | -31.6 | -59.2 | -42.6 | -49.2 | -12.5 | -22.8 | -16.5 | -9.1 | -19.9 | -8.9 | -8.3 | -8.4 | -5.1 | -14.3 | -6.5 | -6.4 | -7.0 | -2.7 |
| `zgap@0.05` | 250x4 | 0.38 | -2.7 | 4.7 | 9.0 | 4.5 | -14.4 | 9.1 | -7.0 | -0.5 | -4.4 | 1.4 | -10.1 | -3.8 | -2.6 | -1.1 | -8.4 | -5.0 | -6.0 | -5.3 | 0.6 |

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
| `hush@d=2/quiet=5/z=0.05/tol=0.3` | 250x4 | 3.60 | 2.5 |
