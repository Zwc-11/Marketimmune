//! Integer types for prices, sizes and identifiers, and exact decimal parsing.
//!
//! Prices are `Tick`s and sizes are `Lots`: integers on a fixed decimal grid per
//! asset. A float never enters the book, so a level can never fail to empty or
//! two equal prices compare unequal after rounding.

use std::fmt;

/// Price in units of `10^-px_decimals` of the quote currency.
pub type Tick = i64;
/// Size in units of `10^-sz_decimals` of the base asset.
pub type Lots = u64;
/// Exchange-assigned order id.
pub type Oid = u64;
/// Interned wallet address (see [`crate::Wallets`]).
pub type UserId = u32;

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub enum Side {
    Bid,
    Ask,
}

impl Side {
    pub fn opposite(self) -> Side {
        match self {
            Side::Bid => Side::Ask,
            Side::Ask => Side::Bid,
        }
    }

    /// Hyperliquid's wire letter: `B` for bids/buys, `A` for asks/sells.
    pub fn from_hl(letter: &str) -> Option<Side> {
        match letter {
            "B" => Some(Side::Bid),
            "A" => Some(Side::Ask),
            _ => None,
        }
    }
}

impl fmt::Display for Side {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Side::Bid => "B",
            Side::Ask => "A",
        })
    }
}

/// One execution: a taker order consumed `lots` of a resting maker order.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Fill {
    pub maker_oid: Oid,
    pub maker: UserId,
    pub taker_oid: Oid,
    pub taker: UserId,
    /// Side of the taker (a `Bid` taker lifts asks).
    pub taker_side: Side,
    pub tick: Tick,
    pub lots: Lots,
}

/// Decimal grid of one asset.
///
/// Hyperliquid perps quote sizes with `sz_decimals` decimals and prices with at
/// most `6 - sz_decimals` decimals (and at most 5 significant figures). Using the
/// maximum price decimals as the grid represents every valid price exactly.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Scale {
    pub px_decimals: u32,
    pub sz_decimals: u32,
}

impl Scale {
    /// Grid for a Hyperliquid perp with the given `szDecimals` from `meta`.
    pub fn perp(sz_decimals: u32) -> Scale {
        Scale { px_decimals: 6u32.saturating_sub(sz_decimals), sz_decimals }
    }

    pub fn px_to_tick(&self, s: &str) -> Result<Tick, DecimalError> {
        parse_fixed(s, self.px_decimals)
    }

    pub fn sz_to_lots(&self, s: &str) -> Result<Lots, DecimalError> {
        let v = parse_fixed(s, self.sz_decimals)?;
        u64::try_from(v).map_err(|_| DecimalError::Negative)
    }

    /// Price of a tick as a float, for output only.
    pub fn tick_to_f64(&self, t: Tick) -> f64 {
        t as f64 / 10f64.powi(self.px_decimals as i32)
    }
}

#[derive(Clone, Debug, PartialEq, Eq, thiserror::Error)]
pub enum DecimalError {
    #[error("empty or malformed decimal")]
    Malformed,
    #[error("more significant decimals than the grid allows")]
    TooPrecise,
    #[error("value out of range")]
    Overflow,
    #[error("negative value where a size was expected")]
    Negative,
}

/// Parse a decimal string onto a grid with `decimals` places, exactly.
///
/// `parse_fixed("96543.21", 2) == Ok(9654321)`; trailing zeros beyond the grid
/// are accepted (`"1.2300"` at 2 places is `123`), other extra digits are an error.
pub fn parse_fixed(s: &str, decimals: u32) -> Result<i64, DecimalError> {
    let (neg, body) = match s.as_bytes().first() {
        Some(b'-') => (true, &s[1..]),
        _ => (false, s),
    };
    let (int_part, frac_part) = match body.split_once('.') {
        Some((i, f)) => (i, f),
        None => (body, ""),
    };
    if int_part.is_empty() && frac_part.is_empty() {
        return Err(DecimalError::Malformed);
    }
    if !int_part.bytes().all(|b| b.is_ascii_digit()) || !frac_part.bytes().all(|b| b.is_ascii_digit()) {
        return Err(DecimalError::Malformed);
    }
    let d = decimals as usize;
    let (kept, dropped) = frac_part.split_at(frac_part.len().min(d));
    if dropped.bytes().any(|b| b != b'0') {
        return Err(DecimalError::TooPrecise);
    }
    let mut v: i64 = 0;
    for b in int_part.bytes().chain(kept.bytes()) {
        v = v.checked_mul(10).and_then(|x| x.checked_add((b - b'0') as i64)).ok_or(DecimalError::Overflow)?;
    }
    for _ in kept.len()..d {
        v = v.checked_mul(10).ok_or(DecimalError::Overflow)?;
    }
    Ok(if neg { -v } else { v })
}

/// Decode the Albers et al. fixed-point `u32`: top 3 bits are the number of
/// decimals, low 29 bits the integer value. Returns `(value, decimals)`.
pub fn decode_albers_fixed(encoded: u32) -> (u32, u32) {
    (encoded & 0x1FFF_FFFF, encoded >> 29)
}

/// Move an Albers-encoded value onto a grid with `grid_decimals` places.
pub fn albers_to_grid(encoded: u32, grid_decimals: u32) -> Result<i64, DecimalError> {
    let (value, dec) = decode_albers_fixed(encoded);
    if dec > grid_decimals {
        let div = 10i64.pow(dec - grid_decimals);
        let v = value as i64;
        if v % div != 0 {
            return Err(DecimalError::TooPrecise);
        }
        return Ok(v / div);
    }
    (value as i64).checked_mul(10i64.pow(grid_decimals - dec)).ok_or(DecimalError::Overflow)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_exactly() {
        assert_eq!(parse_fixed("96543.21", 2), Ok(9_654_321));
        assert_eq!(parse_fixed("0.001", 5), Ok(100));
        assert_eq!(parse_fixed("5", 3), Ok(5_000));
        assert_eq!(parse_fixed("1.2300", 2), Ok(123));
        assert_eq!(parse_fixed(".5", 1), Ok(5));
        assert_eq!(parse_fixed("-2.5", 1), Ok(-25));
        assert_eq!(parse_fixed("1.2345", 2), Err(DecimalError::TooPrecise));
        assert_eq!(parse_fixed("", 2), Err(DecimalError::Malformed));
        assert_eq!(parse_fixed("1e5", 2), Err(DecimalError::Malformed));
        assert_eq!(parse_fixed("99999999999999999999", 0), Err(DecimalError::Overflow));
    }

    #[test]
    fn perp_scale() {
        let btc = Scale::perp(5); // BTC szDecimals = 5 -> 1 price decimal
        assert_eq!(btc.px_to_tick("96543.5"), Ok(965_435));
        assert_eq!(btc.sz_to_lots("0.00123"), Ok(123));
        assert_eq!(btc.sz_to_lots("-1"), Err(DecimalError::Negative));
    }

    #[test]
    fn albers_encoding() {
        // Example from the dataset's SCHEMA.md: 96,543.21 with 2 decimals.
        let enc = (2u32 << 29) | 9_654_321;
        assert_eq!(enc, 0x4093_5031);
        assert_eq!(decode_albers_fixed(enc), (9_654_321, 2));
        assert_eq!(albers_to_grid(enc, 2), Ok(9_654_321));
        assert_eq!(albers_to_grid(enc, 3), Ok(96_543_210));
        assert_eq!(albers_to_grid((3 << 29) | 1_500, 1), Ok(15));
        assert_eq!(albers_to_grid((3 << 29) | 1_501, 1), Err(DecimalError::TooPrecise));
    }
}
