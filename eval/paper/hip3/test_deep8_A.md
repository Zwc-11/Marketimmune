Segments (hours): test/seg-20261109T0129 2.00, test/seg-20261109T0330 2.00, test/seg-20261109T0531 2.00, test/seg-20261109T0732 2.00, test/seg-20261109T0932 2.00, test/seg-20261109T1133 2.00, test/seg-20261109T1334 1.92. Latency 200 ms; fees 0.3 / 0.9 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 0 of 3 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | test/seg-20261109T0129 | test/seg-20261109T0330 | test/seg-20261109T0531 | test/seg-20261109T0732 | test/seg-20261109T0932 | test/seg-20261109T1133 | test/seg-20261109T1334 |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| hush | `hush@d=8/quiet=5/tol=0.3` | 250x4 | 0.65 | -8.2 | -8.2 | yes | 8.5 | 2.8 | -12.3 | -24.8 | -43.4 | 15.3 | -3.5 |
| touch | `touch` | 250x4 | 0.08 | -498.6 | -498.6 | yes | -388.9 | -226.2 | -285.2 | -425.8 | -327.7 | -392.8 | -1,481.8 |

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | test/seg-20261109T0129 | test/seg-20261109T0330 | test/seg-20261109T0531 | test/seg-20261109T0732 | test/seg-20261109T0932 | test/seg-20261109T1133 | test/seg-20261109T1334 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hush@d=8/quiet=5/tol=0.3` | 250x4 | 0.65 | -8.2 | 8.5 | 2.8 | -12.3 | -24.8 | -43.4 | 15.3 | -3.5 |
| `hush@d=8/quiet=0/tol=0.3` | 250x4 | 0.26 | -36.5 | -6.6 | 0.9 | -19.3 | -50.4 | -33.9 | 23.3 | -174.8 |
| `touch` | 250x4 | 0.08 | -498.6 | -388.9 | -226.2 | -285.2 | -425.8 | -327.7 | -392.8 | -1,481.8 |

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
