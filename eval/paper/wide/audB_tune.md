Segments (hours): test/seg-20261109T205504-741facb4 2.00, test/seg-20261109T225523-bfcba6ca 2.00, test/seg-20261110T005608-825965b3 1.61, test/seg-20261110T023827-65c867b8 2.00, test/seg-20261110T043923-22d8f7fe 2.00, test/seg-20261110T064034-e89a95a6 2.00, test/seg-20261110T084147-435199f9 2.00, test/seg-20261110T104313-46efd58d 2.00. Latency 200 ms; fees 0.3 / 0.9 bp. Configs: 250x4 (quote USD x quotes a coin), budget 5000.0 USD a strategy. Only settings at or under 1.0 orders per USD filled (Hyperliquid's rate limit) are selected; 0 of 5 were over it.

| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | test/seg-20261109T205504-741facb4 | test/seg-20261109T225523-bfcba6ca | test/seg-20261110T005608-825965b3 | test/seg-20261110T023827-65c867b8 | test/seg-20261110T043923-22d8f7fe | test/seg-20261110T064034-e89a95a6 | test/seg-20261110T084147-435199f9 | test/seg-20261110T104313-46efd58d |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| hush | `hush@d=12/quiet=0/tol=0.3` | 250x4 | 0.75 | 0.2 | 0.2 | yes | -8.3 | -6.2 | 19.5 | 8.1 | -2.6 | -1.5 | 6.6 | -10.3 |
| mm | `mm@8` | 250x4 | 0.83 | -9.1 | -9.1 | yes | -8.9 | -5.2 | -26.4 | -12.2 | -6.5 | -5.1 | -2.1 | -9.8 |
| touch | `touch` | 250x4 | 0.40 | -17.0 | -17.0 | yes | -25.5 | -23.0 | -11.5 | -17.1 | -6.8 | -10.8 | -12.8 | -27.2 |

Every setting within the rate limit, $ an hour (all segments, then each):

| strategy | config | orders per $ | all | test/seg-20261109T205504-741facb4 | test/seg-20261109T225523-bfcba6ca | test/seg-20261110T005608-825965b3 | test/seg-20261110T023827-65c867b8 | test/seg-20261110T043923-22d8f7fe | test/seg-20261110T064034-e89a95a6 | test/seg-20261110T084147-435199f9 | test/seg-20261110T104313-46efd58d |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hush@d=12/quiet=0/tol=0.3` | 250x4 | 0.75 | 0.2 | -8.3 | -6.2 | 19.5 | 8.1 | -2.6 | -1.5 | 6.6 | -10.3 |
| `hush@d=6/quiet=0/tol=0.3` | 250x4 | 0.56 | -3.8 | -17.4 | 1.4 | 7.7 | -9.1 | -0.5 | 1.1 | -4.5 | -6.8 |
| `hush@d=8/quiet=0/tol=0.3` | 250x4 | 0.63 | -8.3 | -22.5 | -11.6 | -1.4 | -7.4 | 2.7 | -7.0 | -7.5 | -10.9 |
| `mm@8` | 250x4 | 0.83 | -9.1 | -8.9 | -5.2 | -26.4 | -12.2 | -6.5 | -5.1 | -2.1 | -9.8 |
| `touch` | 250x4 | 0.40 | -17.0 | -25.5 | -23.0 | -11.5 | -17.1 | -6.8 | -10.8 | -12.8 | -27.2 |

Over the rate limit (not selectable), best first:

| strategy | config | orders per $ | $/h |
|---|---|---:|---:|
