import { describe, expect, it } from 'vitest';
import fixture from './__fixtures__/parity.json';
import { calibrate, ObliviousModel } from './obliviousTrees';
import { OfiWindows } from './ofi';

// Fixture written by `python -m marketimmune.cli.make_parity_fixtures` from the
// Python feature and model code this file must agree with.

describe('OfiWindows matches l2_rows_with_ofi', () => {
    it('reproduces event and 1s/5s/10s windows row by row', () => {
        const windows = new OfiWindows();
        fixture.ofi.rows.forEach((row, i) => {
            const got = windows.push({
                ts: row.ts_ms,
                bidPx: row.bid_px,
                bidSz: row.bid_sz,
                askPx: row.ask_px,
                askSz: row.ask_sz,
            });
            const want = fixture.ofi.expected[i];
            expect(got.event).toBeCloseTo(want.ofi_event, 12);
            expect(got.ofi1s).toBeCloseTo(want.ofi_1s, 12);
            expect(got.ofi5s).toBeCloseTo(want.ofi_5s, 12);
            expect(got.ofi10s).toBeCloseTo(want.ofi_10s, 12);
        });
    });

    it('keeps only the last 10 s of events', () => {
        const windows = new OfiWindows();
        for (let t = 0; t < 60_000; t += 100) {
            windows.push({ ts: t, bidPx: 1, bidSz: 1, askPx: 2, askSz: 1 });
        }
        expect(windows.size).toBeLessThanOrEqual(101);
    });
});

describe('ObliviousModel matches CatBoost predict_proba', () => {
    const model = ObliviousModel.fromCompact(fixture.model.model);

    it('scores every probe row to 1e-12', () => {
        fixture.model.rows.forEach((row, i) => {
            expect(model.probability(row)).toBeCloseTo(fixture.model.expected_raw[i], 12);
        });
    });

    it('applies the isotonic calibrator like IsotonicCalibrator.transform_one', () => {
        fixture.model.expected_raw.forEach((raw, i) => {
            expect(calibrate(fixture.model.calibrator, raw)).toBeCloseTo(
                fixture.model.expected_calibrated[i],
                12,
            );
        });
    });

    it('rejects artifacts in another format', () => {
        expect(() => ObliviousModel.fromCompact({ format: 'x' })).toThrow(/marketimmune/);
    });
});
