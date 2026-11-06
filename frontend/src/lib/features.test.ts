import { describe, expect, it } from 'vitest';
import { bookTop, featureValues, FEATURE_NAMES, vectorFor } from './features';

describe('live feature names', () => {
    it('lists exactly what featureValues computes, and refuses any other column', () => {
        const top = bookTop(0, 99, 1, 101, 1)!;
        const values = featureValues({ px: 100, sz: 1, makerSide: 1, feeBps: 0 }, top, { event: 0, ofi1s: 0, ofi5s: 0, ofi10s: 0 }, {
            basisBps: 0, funding: 0, openInterest: 0, premium: 0,
        });
        expect(Object.keys(values)).toEqual([...FEATURE_NAMES]);
        expect(() => vectorFor(['sz', 'nope'], values)).toThrow('nope');
    });
});
