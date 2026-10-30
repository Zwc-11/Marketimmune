# Optional own node (Phase 3)

One to two weeks of a non-validating node, only to measure the error of the
nonce-based arrival estimates (Lesson 3.3) against the node's own record of
when each transaction reached it.

- Hardware (from the plan): 16 vCPU, 128 GB RAM, 500 GB SSD, Ubuntu 24.04;
  output is roughly 100 GB/day, so prune aggressively.
- Software: https://github.com/hyperliquid-dex/node (follow its README for the
  current flags; order statuses, raw book diffs and fills by block are the
  outputs this project uses).
- Peering: the public p2p network. The Foundation non-validating node is not an
  option (10,000 staked HYPE, maker-tier volume, and it excludes certain
  activities involving Ontario; see docs/jurisdiction.md).
- Validation: compare each action's node arrival time with `nonce + lat_s` for
  clock signers; the residual's spread is the sigma used in E1a (Lesson 4.4).

Config and a pruner script land here when Phase 3 starts.
