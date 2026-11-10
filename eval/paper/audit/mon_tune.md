Segments (hours): mon/seg-20261109T0129 2.00, mon/seg-20261109T0330 2.00, mon/seg-20261109T0531 2.00, mon/seg-20261109T0732 2.00, mon/seg-20261109T0932 2.00, mon/seg-20261109T1133 2.00, mon/seg-20261109T1334 1.92. Latency 200 ms; fees 0.3 / 0.9 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 4 of 5 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | mon/seg-20261109T0129 | mon/seg-20261109T0330 | mon/seg-20261109T0531 | mon/seg-20261109T0732 | mon/seg-20261109T0932 | mon/seg-20261109T1133 | mon/seg-20261109T1334 |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| hush | `hush@d=8/quiet=0/tol=0.3` | 250x4 | 0.91 | -7.3 | -7.3 | yes | -17.6 | 6.2 | 7.4 | 5.7 | -11.1 | -7.5 | -35.3 |

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | mon/seg-20261109T0129 | mon/seg-20261109T0330 | mon/seg-20261109T0531 | mon/seg-20261109T0732 | mon/seg-20261109T0932 | mon/seg-20261109T1133 | mon/seg-20261109T1334 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hush@d=8/quiet=0/tol=0.3` | 250x4 | 0.91 | -7.3 | -17.6 | 6.2 | 7.4 | 5.7 | -11.1 | -7.5 | -35.3 |

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
| `hush@d=12/quiet=0/tol=0.3` | 250x4 | 1.39 | -5.4 |
| `hush@d=8/quiet=0/k=10/tol=0.3` | 250x4 | 3.31 | -5.9 |
| `hush@d=12/quiet=0/k=10/tol=0.3` | 250x4 | 4.35 | -7.0 |
| `hush@d=8/quiet=0/k=6/tol=0.3` | 250x4 | 2.16 | -9.8 |
