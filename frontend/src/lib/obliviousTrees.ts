// Browser evaluator for the exported CatBoost markout model.
//
// Mirrors marketimmune.models.oblivious_trees: each symmetric tree's leaf is the
// bit pattern of its (feature > border) tests, compared in float32 like CatBoost.
// Trees are flattened into typed arrays once, so scoring a fill is a tight loop
// with no allocation (~150 trees x depth 6 => ~1k comparisons).

export const COMPACT_FORMAT = 'marketimmune.oblivious.v1';

export interface IsotonicArtifact {
    enabled: boolean;
    x: number[];
    y: number[];
}

export interface CompactModel {
    format: string;
    feature_columns: string[];
    scale: number;
    bias: number;
    trees: { f: number[]; b: number[]; v: number[] }[];
    decision_threshold?: number | null;
    calibrator?: IsotonicArtifact;
    model_name?: string | null;
    coin?: string | null;
    horizon?: string | null;
    dataset_label?: string | null;
    cv_scheme?: string | null;
    holdout?: {
        pr_auc?: number | null;
        markout_lift_bps?: number | null;
        lift_vs_event_ofi_bps?: number | null;
    };
}

export class ObliviousModel {
    readonly featureColumns: readonly string[];
    readonly treeCount: number;
    private readonly depths: Int32Array;
    private readonly splitOffsets: Int32Array;
    private readonly leafOffsets: Int32Array;
    private readonly features: Int32Array;
    private readonly borders: Float32Array;
    private readonly leaves: Float64Array;
    private readonly scratch: Float32Array;

    private constructor(private readonly compact: CompactModel) {
        const trees = compact.trees;
        this.featureColumns = compact.feature_columns;
        this.treeCount = trees.length;
        this.depths = new Int32Array(trees.length);
        this.splitOffsets = new Int32Array(trees.length);
        this.leafOffsets = new Int32Array(trees.length);
        let splits = 0;
        let leaves = 0;
        trees.forEach((tree, i) => {
            if (tree.f.length !== tree.b.length || tree.v.length !== 1 << tree.f.length) {
                throw new Error(`tree ${i} has inconsistent splits and leaves`);
            }
            this.depths[i] = tree.f.length;
            this.splitOffsets[i] = splits;
            this.leafOffsets[i] = leaves;
            splits += tree.f.length;
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
        this.scratch = new Float32Array(compact.feature_columns.length);
    }

    static fromCompact(payload: unknown): ObliviousModel {
        const compact = payload as CompactModel;
        if (!compact || compact.format !== COMPACT_FORMAT) {
            throw new Error(`expected a ${COMPACT_FORMAT} model artifact`);
        }
        if (!Array.isArray(compact.trees) || !Array.isArray(compact.feature_columns)) {
            throw new Error('model artifact is missing trees or feature_columns');
        }
        return new ObliviousModel(compact);
    }

    get meta(): Omit<CompactModel, 'trees'> {
        const { trees: _trees, ...meta } = this.compact;
        return meta;
    }

    /** Log-odds for one row; null/NaN features fail every split (CatBoost "Min"). */
    raw(row: ArrayLike<number | null>): number {
        const x = this.scratch;
        for (let i = 0; i < x.length; i += 1) {
            const value = row[i];
            x[i] = value === null || value === undefined ? Number.NaN : value;
        }
        let total = 0;
        for (let t = 0; t < this.treeCount; t += 1) {
            const offset = this.splitOffsets[t];
            const depth = this.depths[t];
            let index = 0;
            for (let d = 0; d < depth; d += 1) {
                if (x[this.features[offset + d]] > this.borders[offset + d]) index |= 1 << d;
            }
            total += this.leaves[this.leafOffsets[t] + index];
        }
        return this.compact.scale * total + this.compact.bias;
    }

    probability(row: ArrayLike<number | null>): number {
        return 1 / (1 + Math.exp(-this.raw(row)));
    }
}

/** Same piecewise-linear map as IsotonicCalibrator.transform_one. */
export function calibrate(calibrator: IsotonicArtifact | undefined, probability: number): number {
    const p = clamp01(probability);
    if (!calibrator || !calibrator.enabled || calibrator.x.length === 0) return p;
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
