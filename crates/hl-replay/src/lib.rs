//! `hl-replay`: rebuild Hyperliquid's order book block by block.
//!
//! - [`book`]: order-by-order book with price-time priority (sorted price ladders
//!   of slab FIFO queues).
//! - [`engine`]: apply a consensus batch in HyperCore's class order
//!   (post-only, then cancels, then takers) — match mode.
//! - [`io`]: streaming readers for the S3 archives.
//! - [`types`]: integer prices and sizes, exact decimal parsing.
//!
//! Outcome mode (apply recorded statuses and book diffs), signer recovery,
//! episode detection and strategy injection land in Phase 1 and later; see the
//! repository README for status.

pub mod book;
pub mod engine;
pub mod io;
pub mod types;

pub use book::{Book, MatchOut, OrderView, Stp};
pub use engine::{Action, BatchOut, Cls, EngineConfig, Op, Status, Tif, apply_batch};
pub use types::{Fill, Lots, Oid, Scale, Side, Tick, UserId};

use rustc_hash::FxHashMap;

/// 20-byte wallet address.
pub type Address = [u8; 20];

/// Interns wallet addresses to dense `u32` ids so book nodes stay small.
#[derive(Clone, Debug, Default)]
pub struct Wallets {
    ids: FxHashMap<Address, UserId>,
    addrs: Vec<Address>,
}

impl Wallets {
    pub fn new() -> Wallets {
        Wallets::default()
    }

    pub fn intern(&mut self, a: Address) -> UserId {
        let next = self.addrs.len();
        *self.ids.entry(a).or_insert_with(|| {
            self.addrs.push(a);
            UserId::try_from(next).expect("more than u32::MAX wallets")
        })
    }

    /// Intern a `0x`-prefixed hex address (case-insensitive).
    pub fn intern_hex(&mut self, s: &str) -> Option<UserId> {
        parse_address(s).map(|a| self.intern(a))
    }

    /// Address of an id this table issued.
    pub fn address(&self, id: UserId) -> &Address {
        &self.addrs[id as usize]
    }
}

/// Parse `0x` + 40 hex digits.
pub fn parse_address(s: &str) -> Option<Address> {
    let hex = s.strip_prefix("0x").or_else(|| s.strip_prefix("0X"))?;
    if hex.len() != 40 {
        return None;
    }
    let mut out = [0u8; 20];
    for (o, pair) in out.iter_mut().zip(hex.as_bytes().chunks_exact(2)) {
        *o = ((pair[0] as char).to_digit(16)? * 16 + (pair[1] as char).to_digit(16)?) as u8;
    }
    Some(out)
}

pub fn format_address(a: &Address) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut s = String::with_capacity(42);
    s.push_str("0x");
    for &b in a {
        s.push(HEX[(b >> 4) as usize] as char);
        s.push(HEX[(b & 0xf) as usize] as char);
    }
    s
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wallets_intern_once() {
        let mut w = Wallets::new();
        let a = w.intern_hex("0x31ca8395cf837de08b24da3f660e77761dfb974b").unwrap();
        let b = w.intern_hex("0x31CA8395CF837DE08B24DA3F660E77761DFB974B").unwrap();
        let c = w.intern_hex("0x6ba889db7f923622d3548f621ecc2054b80c1817").unwrap();
        assert_eq!((a, b, c), (0, 0, 1));
        assert_eq!(format_address(w.address(0)), "0x31ca8395cf837de08b24da3f660e77761dfb974b");
        assert!(parse_address("0x123").is_none());
        assert!(parse_address("31ca8395cf837de08b24da3f660e77761dfb974b").is_none());
    }
}
