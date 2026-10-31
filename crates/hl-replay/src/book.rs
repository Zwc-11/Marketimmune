//! Order-by-order limit order book with price-time priority.
//!
//! Each side is a `BTreeMap` of price levels keyed by [`key`], which sorts both sides
//! worst to best, so the touch is always `last()`. A level is a FIFO queue threaded
//! through a slab of nodes linked by `u32` indices, with a free list for reuse. An
//! `FxHashMap<Oid, u32>` finds any order's slot, so cancelling from the middle of a
//! queue is O(1) after the lookup.
//!
//! NOTE: a sorted `Vec` of levels (touch at the end) measured 20-26% faster on the dense
//! synthetic stream and 2x on top-N reads, but 6.5-10x slower once a side holds 10k+
//! levels with activity spread across them: every new or emptied level shifts all
//! better ones. Switch only after profiling real books.
//!
//! Callers are trusted: adding a duplicate id or zero lots panics. The engine checks
//! both before it adds; the Python bindings validate their input.

use std::collections::{BTreeMap, btree_map, hash_map};
use std::iter;

use rustc_hash::FxHashMap;

use crate::types::{Fill, Lots, Oid, Side, Tick, UserId};

/// Sentinel slab index meaning "no node".
const NIL: u32 = u32::MAX;

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

/// One price level: its queue's head and tail nodes plus cached aggregates.
#[derive(Clone, Copy, Debug)]
struct Level {
    tick: Tick,
    /// Sum of resting lots.
    total: Lots,
    head: u32,
    tail: u32,
    /// Number of resting orders.
    count: u32,
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

/// Full depth, every order, in priority order: bids best (highest) first,
/// asks best (lowest) first, each level's orders front of queue first.
pub type Snapshot = (Vec<(Tick, Vec<(Oid, Lots)>)>, Vec<(Tick, Vec<(Oid, Lots)>)>);

/// Map key that sorts a side's levels worst to best. `!tick` reverses the order of
/// asks without the overflow that `-tick` has at `i64::MIN`.
fn key(side: Side, tick: Tick) -> i64 {
    match side {
        Side::Bid => tick,
        Side::Ask => !tick,
    }
}

#[derive(Clone, Debug, Default)]
pub struct Book {
    nodes: Vec<Node>,
    free: Vec<u32>,
    index: FxHashMap<Oid, u32>,
    /// Levels per side, indexed by `Side as usize`, keyed by [`key`]: the touch is `last()`.
    levels: [BTreeMap<i64, Level>; 2],
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

    /// Append an order to the back of its price level's queue.
    ///
    /// Does not check whether the order crosses; callers that need post-only
    /// semantics check [`Book::crosses`] first.
    pub fn add(&mut self, oid: Oid, user: UserId, side: Side, tick: Tick, lots: Lots) {
        assert!(lots > 0, "order {oid}: size is zero");
        let hash_map::Entry::Vacant(slot) = self.index.entry(oid) else {
            panic!("order {oid} is already resting")
        };
        let lvl = self.levels[side as usize].entry(key(side, tick)).or_insert(Level {
            tick,
            total: 0,
            head: NIL,
            tail: NIL,
            count: 0,
        });
        let node = Node { oid, user, lots, tick, side, prev: lvl.tail, next: NIL };
        let idx = match self.free.pop() {
            Some(i) => {
                self.nodes[i as usize] = node;
                i
            }
            None => {
                assert!(self.nodes.len() < NIL as usize, "more than u32::MAX - 1 resting orders");
                self.nodes.push(node);
                self.nodes.len() as u32 - 1
            }
        };
        match lvl.tail {
            NIL => lvl.head = idx,
            t => self.nodes[t as usize].next = idx,
        }
        lvl.tail = idx;
        lvl.total += lots;
        lvl.count += 1;
        slot.insert(idx);
    }

    /// Unlink the node at `idx` from its level and free its slot. The caller has
    /// already dropped it from the index.
    fn unlink(&mut self, idx: u32) -> Node {
        let n = self.nodes[idx as usize];
        let btree_map::Entry::Occupied(mut level) = self.levels[n.side as usize].entry(key(n.side, n.tick))
        else {
            panic!("order {}: its level is missing", n.oid)
        };
        let lvl = level.get_mut();
        match n.prev {
            NIL => lvl.head = n.next,
            p => self.nodes[p as usize].next = n.next,
        }
        match n.next {
            NIL => lvl.tail = n.prev,
            x => self.nodes[x as usize].prev = n.prev,
        }
        lvl.total -= n.lots;
        lvl.count -= 1;
        if lvl.count == 0 {
            level.remove();
        }
        self.free.push(idx);
        n
    }

    /// Cancel a resting order. Returns its remaining size, or `None` if it is
    /// not on the book (already filled, already cancelled, or never rested).
    pub fn cancel(&mut self, oid: Oid) -> Option<Lots> {
        let idx = self.index.remove(&oid)?;
        Some(self.unlink(idx).lots)
    }

    /// Shrink a resting order in place, keeping its queue position (a partial
    /// fill seen in book diffs). Size zero removes it. Returns the old size.
    pub fn reduce(&mut self, oid: Oid, lots: Lots) -> Lots {
        let idx = *self.index.get(&oid).unwrap_or_else(|| panic!("order {oid} is not on the book"));
        let n = &mut self.nodes[idx as usize];
        let old = n.lots;
        assert!(lots <= old, "order {oid}: size can only shrink in place ({old} -> {lots})");
        if lots == 0 {
            self.cancel(oid);
            return old;
        }
        n.lots = lots;
        let (side, tick) = (n.side, n.tick);
        let lvl =
            self.levels[side as usize].get_mut(&key(side, tick)).expect("a resting order's level exists");
        lvl.total -= old - lots;
        old
    }

    /// Would an order on `side` at `tick` execute against the other side?
    pub fn crosses(&self, side: Side, tick: Tick) -> bool {
        let maker = side.opposite();
        self.levels[maker as usize].last_key_value().is_some_and(|(&k, _)| k >= key(maker, tick))
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
        let maker_side = side.opposite();
        let limit_key = key(maker_side, limit);
        let Book { nodes, free, index, levels } = self;
        let levels = &mut levels[maker_side as usize];
        while lots > 0 {
            let Some(mut entry) = levels.last_entry().filter(|e| *e.key() >= limit_key) else { break };
            let lvl = entry.get_mut();
            while lots > 0 && lvl.head != NIL {
                let head = lvl.head;
                let maker = nodes[head as usize];
                if stp == Stp::ExpireMaker && maker.user == taker {
                    out.stp_canceled.push(maker.oid);
                } else {
                    let q = maker.lots.min(lots);
                    lots -= q;
                    out.fills.push(Fill {
                        maker_oid: maker.oid,
                        maker: maker.user,
                        taker_oid,
                        taker,
                        taker_side: side,
                        tick: lvl.tick,
                        lots: q,
                    });
                    if q < maker.lots {
                        // The taker is used up inside this maker, which keeps its place.
                        nodes[head as usize].lots -= q;
                        lvl.total -= q;
                        break;
                    }
                }
                // Pop the head: same bookkeeping as `unlink`, without the map lookup.
                lvl.head = maker.next;
                match maker.next {
                    NIL => lvl.tail = NIL,
                    x => nodes[x as usize].prev = NIL,
                }
                lvl.total -= maker.lots;
                lvl.count -= 1;
                index.remove(&maker.oid);
                free.push(head);
            }
            if lvl.head == NIL {
                entry.remove();
            }
        }
        lots
    }

    /// Best price on `side` and the size resting there.
    pub fn best(&self, side: Side) -> Option<(Tick, Lots)> {
        self.levels[side as usize].last_key_value().map(|(_, l)| (l.tick, l.total))
    }

    pub fn is_crossed(&self) -> bool {
        self.best(Side::Bid).is_some_and(|(b, _)| self.crosses(Side::Bid, b))
    }

    /// Top `n` levels of one side as `(tick, total lots, order count)`, best first.
    pub fn depth(&self, side: Side, n: usize) -> Vec<(Tick, Lots, u32)> {
        self.levels[side as usize].values().rev().take(n).map(|l| (l.tick, l.total, l.count)).collect()
    }

    /// Nodes from slab index `from` on, following `step` until `NIL`.
    fn walk(&self, from: u32, step: fn(&Node) -> u32) -> impl Iterator<Item = &Node> {
        let at = move |i: u32| (i != NIL).then(|| &self.nodes[i as usize]);
        iter::successors(at(from), move |n| at(step(n)))
    }

    /// Size resting ahead of `oid` in its level's queue.
    pub fn queue_ahead(&self, oid: Oid) -> Option<Lots> {
        let n = &self.nodes[*self.index.get(&oid)? as usize];
        Some(self.walk(n.prev, |n| n.prev).map(|n| n.lots).sum())
    }

    /// Orders at one level, front of the queue first.
    pub fn level_orders(&self, side: Side, tick: Tick) -> Vec<OrderView> {
        let head = self.levels[side as usize].get(&key(side, tick)).map_or(NIL, |l| l.head);
        self.walk(head, |n| n.next)
            .map(|n| OrderView { oid: n.oid, user: n.user, side: n.side, tick: n.tick, lots: n.lots })
            .collect()
    }

    pub fn snapshot(&self) -> Snapshot {
        let side = |s: Side| -> Vec<(Tick, Vec<(Oid, Lots)>)> {
            let orders = |l: &Level| self.walk(l.head, |n| n.next).map(|n| (n.oid, n.lots)).collect();
            self.levels[s as usize].values().rev().map(|l| (l.tick, orders(l))).collect()
        };
        (side(Side::Bid), side(Side::Ask))
    }

    /// Assert every structural invariant; used by tests.
    pub fn check_invariants(&self) {
        for side in [Side::Bid, Side::Ask] {
            for (&k, l) in &self.levels[side as usize] {
                assert_eq!(k, key(side, l.tick), "{side} {}: filed under the wrong key", l.tick);
                let (mut i, mut prev, mut total, mut count) = (l.head, NIL, 0, 0);
                for n in self.walk(l.head, |n| n.next) {
                    let ok = n.side == side && n.tick == l.tick && n.prev == prev && n.lots > 0;
                    let ok = ok && self.index.get(&n.oid) == Some(&i);
                    assert!(ok, "{side} {}: bad node {i}: {n:?} (prev should be {prev})", l.tick);
                    (i, prev, total, count) = (n.next, i, total + n.lots, count + 1);
                }
                assert!(count > 0 && prev == l.tail, "{side} {}: empty, or bad tail", l.tick);
                assert_eq!((l.total, l.count), (total, count), "{side} {}: cached != walked", l.tick);
            }
        }
        let on_levels: usize = self.levels.iter().flat_map(|m| m.values()).map(|l| l.count as usize).sum();
        assert_eq!(on_levels, self.index.len(), "orders on levels != orders in index");
        assert_eq!(self.index.len() + self.free.len(), self.nodes.len(), "slab: live + free != allocated");
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn book() -> Book {
        let mut b = Book::new();
        b.add(1, 10, Side::Ask, 101, 5);
        b.add(2, 11, Side::Ask, 101, 3);
        b.add(3, 12, Side::Ask, 102, 4);
        b.add(4, 13, Side::Bid, 99, 7);
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
        assert_eq!(b.best(Side::Ask), Some((102, 2)));
        b.check_invariants();
    }

    #[test]
    fn limit_stops_matching() {
        let mut b = book();
        let mut out = MatchOut::default();
        assert_eq!(b.take(100, 20, Side::Bid, 101, 10, Stp::Off, &mut out), 2);
        assert_eq!(b.best(Side::Ask), Some((102, 4)));
    }

    #[test]
    fn cancel_from_middle_keeps_queue() {
        let mut b = book();
        b.add(5, 14, Side::Ask, 101, 2);
        assert_eq!(b.cancel(2), Some(3));
        assert_eq!(b.cancel(2), None);
        let oids: Vec<_> = b.level_orders(Side::Ask, 101).iter().map(|o| o.oid).collect();
        assert_eq!(oids, vec![1, 5]);
        assert_eq!(b.queue_ahead(5), Some(5));
        b.check_invariants();
    }

    #[test]
    fn reduce_keeps_priority() {
        let mut b = book();
        assert_eq!(b.reduce(1, 2), 5);
        assert_eq!(
            b.level_orders(Side::Ask, 101)[0],
            OrderView { oid: 1, user: 10, side: Side::Ask, tick: 101, lots: 2 }
        );
        assert_eq!(b.best(Side::Ask), Some((101, 5)));
        assert_eq!(b.reduce(1, 0), 2);
        assert!(!b.contains(1));
        b.check_invariants();
    }

    #[test]
    #[should_panic(expected = "order 1: size can only shrink in place (5 -> 6)")]
    fn reduce_rejects_growth() {
        book().reduce(1, 6);
    }

    #[test]
    #[should_panic(expected = "order 1 is already resting")]
    fn rejects_duplicates() {
        book().add(1, 10, Side::Bid, 90, 1);
    }

    #[test]
    #[should_panic(expected = "order 9: size is zero")]
    fn rejects_zero() {
        book().add(9, 10, Side::Bid, 90, 0);
    }

    #[test]
    fn slab_slots_are_reused() {
        let mut b = Book::new();
        for oid in 0..100 {
            b.add(oid, 0, Side::Bid, 50, 1);
            b.cancel(oid).unwrap();
        }
        assert_eq!(b.nodes.len(), 1);
        b.check_invariants();
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
        b.check_invariants();
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
