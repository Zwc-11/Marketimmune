Segments (hours): test/seg-20261109T205504-741facb4 2.00, test/seg-20261109T225523-bfcba6ca 2.00, test/seg-20261110T005608-825965b3 1.61, test/seg-20261110T023827-65c867b8 2.00, test/seg-20261110T043923-22d8f7fe 2.00, test/seg-20261110T064034-e89a95a6 2.00, test/seg-20261110T084147-435199f9 2.00, test/seg-20261110T104313-46efd58d 2.00. Latency 200 ms; fees 0.3 / 0.9 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 0 of 2 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | test/seg-20261109T205504-741facb4 | test/seg-20261109T225523-bfcba6ca | test/seg-20261110T005608-825965b3 | test/seg-20261110T023827-65c867b8 | test/seg-20261110T043923-22d8f7fe | test/seg-20261110T064034-e89a95a6 | test/seg-20261110T084147-435199f9 | test/seg-20261110T104313-46efd58d |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| hush | `hush@d=10/quiet=0/tol=0.3` | 250x4 | 0.76 | -4.1 | -7.0 | no | 6.6 | -9.1 | -6.6 | -9.1 | -2.2 | 6.4 | 1.1 | -20.5 |

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | test/seg-20261109T205504-741facb4 | test/seg-20261109T225523-bfcba6ca | test/seg-20261110T005608-825965b3 | test/seg-20261110T023827-65c867b8 | test/seg-20261110T043923-22d8f7fe | test/seg-20261110T064034-e89a95a6 | test/seg-20261110T084147-435199f9 | test/seg-20261110T104313-46efd58d |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hush@d=10/quiet=0/tol=0.3` | 250x4 | 0.76 | -4.1 | 6.6 | -9.1 | -6.6 | -9.1 | -2.2 | 6.4 | 1.1 | -20.5 |
| `hush@d=10/quiet=0/tol=0.3/stale=30` | 250x4 | 0.68 | -5.0 | -9.6 | -11.1 | -5.6 | -2.0 | 1.3 | 2.5 | -5.5 | -9.9 |

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
