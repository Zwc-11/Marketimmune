// Browser evaluator for the exported CatBoost markout model.
//
// Mirrors marketimmune.serving.oblivious_trees: each symmetric tree's leaf is the
// bit pattern of its (feature > border) tests, compared in float32 like CatBoost.
// Trees are flattened into typed arrays once, so scoring a fill is a tight loop
// with no allocation (~150 trees x depth 6 => ~1k comparisons).

const COMPACT_FORMAT = 'marketimmune.oblivious.v1';

export interface IsotonicArtifact {
    enabled: boolean;
    x: number[];
    y: number[];
}

interface CompactModel {
    format: string;
    feature_columns: string[];
    scale: number;
    bias: number;
    trees: { f: number[]; b: number[]; v: number[] }[];
    decision_threshold?: number | null;
    calibrator?: IsotonicArtifact;
    model_name?: string | null;
}

export class ObliviousModel {
    readonly meta: Omit<CompactModel, 'trees'>;
    readonly treeCount: number;
    private readonly depths: Int32Array;
    private readonly splitOffsets: Int32Array;
    private readonly leafOffsets: Int32Array;
    private readonly features: Int32Array;
    private readonly borders: Float32Array;
    private readonly leaves: Float64Array;
    private readonly scratch: Float32Array;

    static fromCompact(payload: unknown): ObliviousModel {
        const compact = payload as CompactModel | null;
        if (compact?.format !== COMPACT_FORMAT) throw new Error(`expected a ${COMPACT_FORMAT} model artifact`);
        if (!Array.isArray(compact.trees) || !Array.isArray(compact.feature_columns)) {
            throw new Error('model artifact is missing trees or feature_columns');
        }
        return new ObliviousModel(compact);
    }

    private constructor({ trees, ...meta }: CompactModel) {
        this.meta = meta;
        this.treeCount = trees.length;
        this.depths = new Int32Array(trees.length);
        this.splitOffsets = new Int32Array(trees.length);
        this.leafOffsets = new Int32Array(trees.length);
        let splits = 0;
        let leaves = 0;
        trees.forEach((tree, i) => {
            const depth = tree.f.length;
            if (tree.b.length !== depth || tree.v.length !== 1 << depth) {
                throw new Error(`tree ${i} has inconsistent splits and leaves`);
            }
            this.depths[i] = depth;
            this.splitOffsets[i] = splits;
            this.leafOffsets[i] = leaves;
            splits += depth;
            leaves += tree.v.length;
        });
        this.features = new Int32Array(splits);
        this.borders = new Float32Array(splits);
        this.leaves = new Float64Array(leaves);
        trees.forEach((tree, i) => {
            this.features.set(tree.f, this.splitOffsets[i]);
            this.borders.set(tree.b, this.splitOffsets[i]);
            this.leaves.set(tree.v, this.leafOffsets[i]);
        });
        this.scratch = new Float32Array(meta.feature_columns.length);
    }

    get featureColumns(): readonly string[] {
        return this.meta.feature_columns;
    }

    /** Log-odds for one row; null/NaN features fail every split (CatBoost "Min"). */
    raw(row: ArrayLike<number | null>): number {
        const { scratch: x, depths, splitOffsets, leafOffsets, features, borders, leaves } = this;
        if (row.length !== x.length) throw new Error(`expected ${x.length} features, got ${row.length}`);
        for (let i = 0; i < x.length; i += 1) x[i] = row[i] ?? Number.NaN;
        let total = 0;
        for (let t = 0; t < depths.length; t += 1) {
            const end = splitOffsets[t] + depths[t];
            let index = 0;
            for (let s = splitOffsets[t], bit = 1; s < end; s += 1, bit <<= 1) {
                if (x[features[s]] > borders[s]) index |= bit;
            }
            total += leaves[leafOffsets[t] + index];
        }
        return this.meta.scale * total + this.meta.bias;
    }

    probability(row: ArrayLike<number | null>): number {
        return 1 / (1 + Math.exp(-this.raw(row)));
    }
}

/** Same piecewise-linear map as IsotonicCalibrator.transform_one. */
export function calibrate(calibrator: IsotonicArtifact | undefined, probability: number): number {
    const p = clamp01(probability);
    if (!calibrator?.enabled || calibrator.x.length === 0) return p;
    const { x, y } = calibrator;
    if (p <= x[0]) return clamp01(y[0]);
    if (p >= x[x.length - 1]) return clamp01(y[y.length - 1]);
    let lo = 0;
    let hi = x.length;
    while (lo < hi) {
        const mid = (lo + hi) >>> 1;
        if (x[mid] < p) lo = mid + 1;
        else hi = mid;
    }
    const left = lo - 1;
    const weight = (p - x[left]) / (x[lo] - x[left]);
    return clamp01(y[left] + (y[lo] - y[left]) * weight);
}

function clamp01(value: number): number {
    return Math.min(1, Math.max(0, value));
}
