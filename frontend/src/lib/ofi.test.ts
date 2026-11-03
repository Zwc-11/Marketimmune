import { describe, expect, it } from 'vitest';

import { OfiWindows } from './ofi';

const snap = (ts: number, bidSz: number) => ({ ts, bidPx: 100, bidSz, askPx: 101, askSz: 1 });

describe('OfiWindows', () => {
    it('restarts after a jump longer than 30 s, like the Silver book reset', () => {
        const ofi = new OfiWindows();
        ofi.push(snap(0, 1));
        expect(ofi.push(snap(1_000, 3)).event).toBeCloseTo(2 / 6);
        const after = ofi.push(snap(31_001, 9));
        expect(after.event).toBe(0);
        expect(after.ofi10s).toBe(0);
        expect(ofi.push(snap(31_500, 10)).event).toBeCloseTo(1 / 21);
    });
});
