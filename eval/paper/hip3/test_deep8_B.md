Segments (hours): test/seg-20261109T0129 2.00, test/seg-20261109T0330 2.00, test/seg-20261109T0531 2.00, test/seg-20261109T0732 2.00, test/seg-20261109T0932 2.00, test/seg-20261109T1133 2.00, test/seg-20261109T1334 1.92. Latency 200 ms; fees 0.3 / 0.9 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 0 of 3 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | test/seg-20261109T0129 | test/seg-20261109T0330 | test/seg-20261109T0531 | test/seg-20261109T0732 | test/seg-20261109T0932 | test/seg-20261109T1133 | test/seg-20261109T1334 |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| mm | `mm@8` | 250x4 | 0.50 | -29.2 | -29.2 | yes | -37.1 | -5.9 | 0.9 | -27.4 | -24.4 | -25.4 | -86.9 |
| zgap | `zgap@0.05` | 250x4 | 0.08 | -172.3 | -172.3 | yes | -149.9 | -76.8 | -97.0 | -154.7 | -130.2 | -115.8 | -494.1 |

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | test/seg-20261109T0129 | test/seg-20261109T0330 | test/seg-20261109T0531 | test/seg-20261109T0732 | test/seg-20261109T0932 | test/seg-20261109T1133 | test/seg-20261109T1334 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `mm@8` | 250x4 | 0.50 | -29.2 | -37.1 | -5.9 | 0.9 | -27.4 | -24.4 | -25.4 | -86.9 |
| `mm@5` | 250x4 | 0.35 | -63.9 | -72.0 | -33.6 | -21.8 | -55.7 | -48.8 | -70.5 | -148.0 |
| `zgap@0.05` | 250x4 | 0.08 | -172.3 | -149.9 | -76.8 | -97.0 | -154.7 | -130.2 | -115.8 | -494.1 |

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
