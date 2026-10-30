//! One price level: a FIFO queue of resting orders, linked through slab indices.

use crate::types::Lots;

/// Sentinel slab index meaning "no node".
pub const NIL: u32 = u32::MAX;

/// Head and tail of a level's queue plus cached aggregates.
///
/// The queue is a doubly linked list whose nodes live in the book's slab, so
/// cancelling from the middle is O(1) and nodes stay contiguous in memory.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Level {
    pub head: u32,
    pub tail: u32,
    /// Sum of resting lots at this level.
    pub total: Lots,
    /// Number of resting orders at this level.
    pub count: u32,
}

impl Level {
    pub const EMPTY: Level = Level { head: NIL, tail: NIL, total: 0, count: 0 };

    pub fn is_empty(&self) -> bool {
        self.head == NIL
    }
}
