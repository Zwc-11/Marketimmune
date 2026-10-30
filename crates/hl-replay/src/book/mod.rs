//! Order-by-order limit order book with price-time priority.
//!
//! Price levels live in a `BTreeMap<Tick, Level>` per side (simple, O(log n));
//! each level is a FIFO queue threaded through a slab of nodes linked by `u32`
//! indices, with a free list for reuse. An `FxHashMap<Oid, u32>` finds any order's
//! slot, so cancelling from the middle of a queue is O(1) after the lookup.
//! A cache-friendly ladder can replace the maps once profiling says so.

pub mod level;

use std::collections::BTreeMap;

use rustc_hash::FxHashMap;

pub use level::{Level, NIL};

use crate::types::{Fill, Lots, Oid, Side, Tick, UserId};

#[derive(Clone, Copy, Debug)]
struct Node {
    oid: Oid,
    user: UserId,
    lots: Lots,
    tick: Tick,
    side: Side,
    prev: u32,
    next: u32,
}

/// Self-trade prevention applied when a taker reaches its own resting order.
///
/// `ExpireMaker` cancels the resting order and keeps matching, which is what
/// the `selfTradeCanceled` status in the order-status data suggests. Which rule
/// Hyperliquid applies is settled by the cross-mode test, not assumed here.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Stp {
    #[default]
    Off,
    ExpireMaker,
}

/// Everything one matching call produced, in execution order.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct MatchOut {
    pub fills: Vec<Fill>,
    /// Resting orders cancelled by self-trade prevention.
    pub stp_canceled: Vec<Oid>,
}

impl MatchOut {
    pub fn clear(&mut self) {
        self.fills.clear();
        self.stp_canceled.clear();
    }
}

/// A resting order as seen from outside the book.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct OrderView {
    pub oid: Oid,
    pub user: UserId,
    pub side: Side,
    pub tick: Tick,
    pub lots: Lots,
}

#[derive(Clone, Debug, PartialEq, Eq, thiserror::Error)]
pub enum BookError {
    #[error("order {0} is already resting")]
    DuplicateOid(Oid),
    #[error("order size is zero")]
    ZeroLots,
    #[error("order {0} is not on the book")]
    UnknownOid(Oid),
    #[error("order {oid}: size can only shrink in place ({old} -> {new})")]
    SizeIncrease { oid: Oid, old: Lots, new: Lots },
}

/// Full depth, every order, in priority order: bids best (highest) first,
/// asks best (lowest) first, each level's orders front of queue first.
pub type Snapshot = (Vec<(Tick, Vec<(Oid, Lots)>)>, Vec<(Tick, Vec<(Oid, Lots)>)>);

#[derive(Clone, Debug, Default)]
pub struct Book {
    nodes: Vec<Node>,
    free: Vec<u32>,
    index: FxHashMap<Oid, u32>,
    bids: BTreeMap<Tick, Level>,
    asks: BTreeMap<Tick, Level>,
}

impl Book {
    pub fn new() -> Book {
        Book::default()
    }

    pub fn with_capacity(orders: usize) -> Book {
        Book {
            nodes: Vec::with_capacity(orders),
            index: FxHashMap::with_capacity_and_hasher(orders, Default::default()),
            ..Book::default()
        }
    }

    /// Number of resting orders.
    pub fn len(&self) -> usize {
        self.index.len()
    }

    pub fn is_empty(&self) -> bool {
        self.index.is_empty()
    }

    /// Is `oid` resting on the book?
    pub fn contains(&self, oid: Oid) -> bool {
        self.index.contains_key(&oid)
    }

    fn alloc(&mut self, n: Node) -> u32 {
        if let Some(i) = self.free.pop() {
            self.nodes[i as usize] = n;
            i
        } else {
            let i = u32::try_from(self.nodes.len()).expect("more than u32::MAX resting orders");
            assert!(i != NIL, "slab index collides with NIL");
            self.nodes.push(n);
            i
        }
    }

    /// Append an order to the back of its price level's queue.
    ///
    /// Does not check whether the order crosses; callers that need post-only
    /// semantics check [`Book::crosses`] first.
    pub fn add(
        &mut self,
        oid: Oid,
        user: UserId,
        side: Side,
        tick: Tick,
        lots: Lots,
    ) -> Result<(), BookError> {
        if lots == 0 {
            return Err(BookError::ZeroLots);
        }
        if self.index.contains_key(&oid) {
            return Err(BookError::DuplicateOid(oid));
        }
        let idx = self.alloc(Node { oid, user, lots, tick, side, prev: NIL, next: NIL });
        let levels = match side {
            Side::Bid => &mut self.bids,
            Side::Ask => &mut self.asks,
        };
        let lvl = levels.entry(tick).or_insert(Level::EMPTY);
        if lvl.tail == NIL {
            lvl.head = idx;
        } else {
            self.nodes[lvl.tail as usize].next = idx;
            self.nodes[idx as usize].prev = lvl.tail;
        }
        lvl.tail = idx;
        lvl.total += lots;
        lvl.count += 1;
        self.index.insert(oid, idx);
        Ok(())
    }

    /// Remove the node at `idx` from its level, the index and the slab.
    fn unlink(&mut self, idx: u32) -> Node {
        let n = self.nodes[idx as usize];
        let levels = match n.side {
            Side::Bid => &mut self.bids,
            Side::Ask => &mut self.asks,
        };
        let lvl = levels.get_mut(&n.tick).expect("a resting node's level exists");
        if n.prev == NIL {
            lvl.head = n.next;
        } else {
            self.nodes[n.prev as usize].next = n.next;
        }
        if n.next == NIL {
            lvl.tail = n.prev;
        } else {
            self.nodes[n.next as usize].prev = n.prev;
        }
        lvl.total -= n.lots;
        lvl.count -= 1;
        if lvl.is_empty() {
            levels.remove(&n.tick);
        }
        self.index.remove(&n.oid);
        self.free.push(idx);
        n
    }

    /// Cancel a resting order. Returns its remaining size, or `None` if it is
    /// not on the book (already filled, already cancelled, or never rested).
    pub fn cancel(&mut self, oid: Oid) -> Option<Lots> {
        let idx = *self.index.get(&oid)?;
        Some(self.unlink(idx).lots)
    }

    /// Shrink a resting order in place, keeping its queue position (a partial
    /// fill seen in book diffs). Size zero removes it. Returns the old size.
    pub fn reduce(&mut self, oid: Oid, new_lots: Lots) -> Result<Lots, BookError> {
        let idx = *self.index.get(&oid).ok_or(BookError::UnknownOid(oid))?;
        let n = self.nodes[idx as usize];
        if new_lots > n.lots {
            return Err(BookError::SizeIncrease { oid, old: n.lots, new: new_lots });
        }
        if new_lots == 0 {
            self.unlink(idx);
            return Ok(n.lots);
        }
        let levels = match n.side {
            Side::Bid => &mut self.bids,
            Side::Ask => &mut self.asks,
        };
        levels.get_mut(&n.tick).expect("a resting node's level exists").total -= n.lots - new_lots;
        self.nodes[idx as usize].lots = new_lots;
        Ok(n.lots)
    }

    /// Would an order on `side` at `tick` execute against the other side?
    pub fn crosses(&self, side: Side, tick: Tick) -> bool {
        match side {
            Side::Bid => self.asks.keys().next().is_some_and(|&a| tick >= a),
            Side::Ask => self.bids.keys().next_back().is_some_and(|&b| tick <= b),
        }
    }

    /// Execute a taker order against the opposite side in price-time priority,
    /// up to `limit`. Appends fills to `out` and returns the unfilled lots.
    ///
    /// Each crossed level is entered once and drained from its head in place, so a
    /// fill costs no map lookup; only an emptied level is removed from the map.
    #[allow(clippy::too_many_arguments)]
    pub fn take(
        &mut self,
        taker_oid: Oid,
        taker: UserId,
        side: Side,
        limit: Tick,
        mut lots: Lots,
        stp: Stp,
        out: &mut MatchOut,
    ) -> Lots {
        let Book { nodes, free, index, bids, asks } = self;
        while lots > 0 {
            let entry = match side {
                Side::Bid => asks.first_entry().filter(|e| *e.key() <= limit),
                Side::Ask => bids.last_entry().filter(|e| *e.key() >= limit),
            };
            let Some(mut entry) = entry else { break };
            let tick = *entry.key();
            let lvl = entry.get_mut();
            while lots > 0 && lvl.head != NIL {
                let head = lvl.head;
                let maker = nodes[head as usize];
                let self_trade = stp == Stp::ExpireMaker && maker.user == taker;
                let q = if self_trade { 0 } else { maker.lots.min(lots) };
                if q > 0 {
                    lots -= q;
                    out.fills.push(Fill {
                        maker_oid: maker.oid,
                        maker: maker.user,
                        taker_oid,
                        taker,
                        taker_side: side,
                        tick,
                        lots: q,
                    });
                }
                if self_trade || q == maker.lots {
                    // Pop the head: same bookkeeping as `unlink`, without the map lookup.
                    lvl.head = maker.next;
                    if maker.next == NIL {
                        lvl.tail = NIL;
                    } else {
                        nodes[maker.next as usize].prev = NIL;
                    }
                    lvl.total -= maker.lots;
                    lvl.count -= 1;
                    index.remove(&maker.oid);
                    free.push(head);
                    if self_trade {
                        out.stp_canceled.push(maker.oid);
                    }
                } else {
                    nodes[head as usize].lots -= q;
                    lvl.total -= q;
                }
            }
            if lvl.head == NIL {
                entry.remove();
            }
        }
        lots
    }

    /// Best bid price and the size resting there.
    pub fn best_bid(&self) -> Option<(Tick, Lots)> {
        self.bids.last_key_value().map(|(&t, l)| (t, l.total))
    }

    /// Best ask price and the size resting there.
    pub fn best_ask(&self) -> Option<(Tick, Lots)> {
        self.asks.first_key_value().map(|(&t, l)| (t, l.total))
    }

    pub fn is_crossed(&self) -> bool {
        matches!((self.best_bid(), self.best_ask()), (Some((b, _)), Some((a, _))) if b >= a)
    }

    /// Top `n` levels of one side as `(tick, total lots, order count)`, best first.
    pub fn depth(&self, side: Side, n: usize) -> Vec<(Tick, Lots, u32)> {
        let f = |(&t, l): (&Tick, &Level)| (t, l.total, l.count);
        match side {
            Side::Bid => self.bids.iter().rev().take(n).map(f).collect(),
            Side::Ask => self.asks.iter().take(n).map(f).collect(),
        }
    }

    pub fn order(&self, oid: Oid) -> Option<OrderView> {
        let n = &self.nodes[*self.index.get(&oid)? as usize];
        Some(OrderView { oid: n.oid, user: n.user, side: n.side, tick: n.tick, lots: n.lots })
    }

    /// Size resting ahead of `oid` in its level's queue.
    pub fn queue_ahead(&self, oid: Oid) -> Option<Lots> {
        let mut i = self.nodes[*self.index.get(&oid)? as usize].prev;
        let mut ahead = 0;
        while i != NIL {
            let n = &self.nodes[i as usize];
            ahead += n.lots;
            i = n.prev;
        }
        Some(ahead)
    }

    /// Orders at one level, front of the queue first.
    pub fn level_orders(&self, side: Side, tick: Tick) -> Vec<OrderView> {
        let levels = match side {
            Side::Bid => &self.bids,
            Side::Ask => &self.asks,
        };
        let mut out = Vec::new();
        let mut i = levels.get(&tick).map_or(NIL, |l| l.head);
        while i != NIL {
            let n = &self.nodes[i as usize];
            out.push(OrderView { oid: n.oid, user: n.user, side: n.side, tick: n.tick, lots: n.lots });
            i = n.next;
        }
        out
    }

    pub fn snapshot(&self) -> Snapshot {
        let side = |it: &mut dyn Iterator<Item = (&Tick, &Level)>| -> Vec<(Tick, Vec<(Oid, Lots)>)> {
            it.map(|(&t, l)| {
                let mut orders = Vec::with_capacity(l.count as usize);
                let mut i = l.head;
                while i != NIL {
                    let n = &self.nodes[i as usize];
                    orders.push((n.oid, n.lots));
                    i = n.next;
                }
                (t, orders)
            })
            .collect()
        };
        (side(&mut self.bids.iter().rev()), side(&mut self.asks.iter()))
    }

    /// Check every structural invariant; used by tests and debug builds.
    pub fn check_invariants(&self) -> Result<(), String> {
        let mut seen = 0usize;
        for (side, levels) in [(Side::Bid, &self.bids), (Side::Ask, &self.asks)] {
            for (&tick, lvl) in levels {
                if lvl.is_empty() {
                    return Err(format!("{side} {tick}: empty level kept"));
                }
                let (mut i, mut prev, mut total, mut count) = (lvl.head, NIL, 0u64, 0u32);
                while i != NIL {
                    let n = self.nodes.get(i as usize).ok_or(format!("dangling index {i}"))?;
                    if n.side != side || n.tick != tick {
                        return Err(format!("order {} filed under {side} {tick}", n.oid));
                    }
                    if n.prev != prev {
                        return Err(format!("order {}: broken prev link", n.oid));
                    }
                    if n.lots == 0 {
                        return Err(format!("order {}: zero lots resting", n.oid));
                    }
                    if self.index.get(&n.oid) != Some(&i) {
                        return Err(format!("order {}: index does not point at its node", n.oid));
                    }
                    total += n.lots;
                    count += 1;
                    prev = i;
                    i = n.next;
                }
                if prev != lvl.tail {
                    return Err(format!("{side} {tick}: tail is not the last node"));
                }
                if total != lvl.total || count != lvl.count {
                    return Err(format!(
                        "{side} {tick}: cached ({}, {}) != walked ({total}, {count})",
                        lvl.total, lvl.count
                    ));
                }
                seen += count as usize;
            }
        }
        if seen != self.index.len() {
            return Err(format!("{seen} orders on levels, {} in index", self.index.len()));
        }
        if self.index.len() + self.free.len() != self.nodes.len() {
            return Err("slab: live + free != allocated".into());
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn book() -> Book {
        let mut b = Book::new();
        b.add(1, 10, Side::Ask, 101, 5).unwrap();
        b.add(2, 11, Side::Ask, 101, 3).unwrap();
        b.add(3, 12, Side::Ask, 102, 4).unwrap();
        b.add(4, 13, Side::Bid, 99, 7).unwrap();
        b
    }

    #[test]
    fn fifo_within_level_then_price() {
        let mut b = book();
        let mut out = MatchOut::default();
        let left = b.take(100, 20, Side::Bid, 102, 10, Stp::Off, &mut out);
        assert_eq!(left, 0);
        let got: Vec<_> = out.fills.iter().map(|f| (f.maker_oid, f.tick, f.lots)).collect();
        assert_eq!(got, vec![(1, 101, 5), (2, 101, 3), (3, 102, 2)]);
        assert_eq!(b.best_ask(), Some((102, 2)));
        b.check_invariants().unwrap();
    }

    #[test]
    fn limit_stops_matching() {
        let mut b = book();
        let mut out = MatchOut::default();
        assert_eq!(b.take(100, 20, Side::Bid, 101, 10, Stp::Off, &mut out), 2);
        assert_eq!(b.best_ask(), Some((102, 4)));
    }

    #[test]
    fn cancel_from_middle_keeps_queue() {
        let mut b = book();
        b.add(5, 14, Side::Ask, 101, 2).unwrap();
        assert_eq!(b.cancel(2), Some(3));
        assert_eq!(b.cancel(2), None);
        let oids: Vec<_> = b.level_orders(Side::Ask, 101).iter().map(|o| o.oid).collect();
        assert_eq!(oids, vec![1, 5]);
        assert_eq!(b.queue_ahead(5), Some(5));
        b.check_invariants().unwrap();
    }

    #[test]
    fn reduce_keeps_priority() {
        let mut b = book();
        assert_eq!(b.reduce(1, 2), Ok(5));
        assert_eq!(
            b.level_orders(Side::Ask, 101)[0],
            OrderView { oid: 1, user: 10, side: Side::Ask, tick: 101, lots: 2 }
        );
        assert_eq!(b.best_ask(), Some((101, 5)));
        assert_eq!(b.reduce(1, 3), Err(BookError::SizeIncrease { oid: 1, old: 2, new: 3 }));
        assert_eq!(b.reduce(1, 0), Ok(2));
        assert!(b.order(1).is_none());
        b.check_invariants().unwrap();
    }

    #[test]
    fn rejects_duplicates_and_zero() {
        let mut b = book();
        assert_eq!(b.add(1, 10, Side::Bid, 90, 1), Err(BookError::DuplicateOid(1)));
        assert_eq!(b.add(9, 10, Side::Bid, 90, 0), Err(BookError::ZeroLots));
    }

    #[test]
    fn slab_slots_are_reused() {
        let mut b = Book::new();
        for oid in 0..100 {
            b.add(oid, 0, Side::Bid, 50, 1).unwrap();
            b.cancel(oid).unwrap();
        }
        assert_eq!(b.nodes.len(), 1);
        b.check_invariants().unwrap();
    }

    #[test]
    fn self_trade_expire_maker() {
        let mut b = book();
        let mut out = MatchOut::default();
        // User 10 owns order 1 at the front of 101; its own taker skips and expires it.
        let left = b.take(100, 10, Side::Bid, 101, 3, Stp::ExpireMaker, &mut out);
        assert_eq!(left, 0);
        assert_eq!(out.stp_canceled, vec![1]);
        assert_eq!(out.fills.len(), 1);
        assert_eq!((out.fills[0].maker_oid, out.fills[0].lots), (2, 3));
        b.check_invariants().unwrap();
    }

    #[test]
    fn crosses_and_depth() {
        let b = book();
        assert!(b.crosses(Side::Bid, 101));
        assert!(!b.crosses(Side::Bid, 100));
        assert!(b.crosses(Side::Ask, 99));
        assert!(!b.crosses(Side::Ask, 100));
        assert_eq!(b.depth(Side::Ask, 5), vec![(101, 8, 2), (102, 4, 1)]);
        assert!(!b.is_crossed());
    }
}
