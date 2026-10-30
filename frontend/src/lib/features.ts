// Live feature vector for one fill, mirroring
// marketimmune.features.hyperliquid_features.prepare_markout_feature_row and the
// top-of-book features in marketimmune.ingest.hyperliquid_archive.BookSnapshot.

import type { OfiValues, TopOfBookSizes } from './ofi';

const BPS = 10_000;

export interface BookTop extends TopOfBookSizes {
    mid: number;
    spreadBps: number;
    microprice: number;
    imbalance: number;
}

export interface AssetFeatures {
    basisBps: number;
    funding: number;
    openInterest: number;
    premium: number;
}

export interface FillInput {
    px: number;
    sz: number;
    makerSide: 1 | -1;
    feeBps: number;
}

export function bookTop(
    ts: number,
    bidPx: number,
    bidSz: number,
    askPx: number,
    askSz: number,
): BookTop | null {
    const total = bidSz + askSz;
    if (!(total > 0) || !(bidPx > 0) || !(askPx > 0)) return null;
    const mid = (bidPx + askPx) / 2;
    return {
        ts,
        bidPx,
        bidSz,
        askPx,
        askSz,
        mid,
        spreadBps: ((askPx - bidPx) / mid) * BPS,
        microprice: (bidPx * askSz + askPx * bidSz) / total,
        imbalance: (bidSz - askSz) / total,
    };
}

export function assetFeatures(ctx: {
    markPx: number;
    oraclePx: number;
    funding: number;
    openInterest: number;
    premium: number;
}): AssetFeatures | null {
    if (!(ctx.oraclePx > 0)) return null;
    return {
        basisBps: ((ctx.markPx - ctx.oraclePx) / ctx.oraclePx) * BPS,
        funding: ctx.funding,
        openInterest: ctx.openInterest,
        premium: ctx.premium,
    };
}

/** Values keyed by the training column names in HYPERLIQUID_MARKOUT_FEATURE_COLUMNS. */
export function featureValues(
    fill: FillInput,
    top: BookTop,
    ofi: OfiValues,
    asset: AssetFeatures,
): Record<string, number> {
    const { mid } = top;
    return {
        sz: fill.sz,
        maker_side: fill.makerSide,
        fee_bps: fill.feeBps,
        l2_spread_bps: top.spreadBps,
        l2_microprice_offset_bps: ((top.microprice - mid) / mid) * BPS,
        l2_top_imbalance: top.imbalance,
        l2_ofi_event: ofi.event,
        l2_ofi_1s: ofi.ofi1s,
        l2_ofi_5s: ofi.ofi5s,
        l2_ofi_10s: ofi.ofi10s,
        fill_vs_mid_bps: ((fill.px - mid) / mid) * BPS * fill.makerSide,
        asset_basis_bps: asset.basisBps,
        asset_funding: asset.funding,
        asset_open_interest: asset.openInterest,
        asset_premium: asset.premium,
    };
}

/** Order values by the model's column list; unknown columns become null (fail splits). */
export function vectorFor(columns: readonly string[], values: Record<string, number>): (number | null)[] {
    return columns.map((name) => (name in values ? values[name] : null));
}
