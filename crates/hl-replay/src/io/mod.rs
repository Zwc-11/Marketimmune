//! Readers for Hyperliquid's archives.
//!
//! Landed so far: streaming LZ4-frame lines. Next (Phase 1): `replica_cmds`
//! blocks to actions, `node_fills_by_block`, the Albers L4 statuses and book
//! diffs, and Parquet output.

pub mod lz4_lines;
