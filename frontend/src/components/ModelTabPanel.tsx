import type { ModelTab } from '../lib/derive';
import {
    benchmarkCompareSeries,
    calibrationEvidence,
    modelThresholdEvidence,
    scenarioLiftSeries,
} from '../lib/derive';
import type { ProductData } from '../routes';
import {
    CalibrationCompare,
    MetricCompareBars,
    ScenarioLiftBars,
    ThresholdBar,
} from './charts';
import { DataPanel } from './ui';

export function ModelTabPanel({
    tab,
    data,
}: {
    tab: ModelTab;
    data: ProductData;
}) {
    const compareRows = benchmarkCompareSeries(data.trainingRuns, data.modelMetrics);
    const threshold = modelThresholdEvidence(data.trainingRuns, data.modelMetrics);
    const calibration = calibrationEvidence(data.modelMetrics);
    const benchmark = data.benchmarkMetrics[0] ?? null;

    if (tab === 'trend') {
        return (
            <DataPanel className="model-tab-panel" title="Metric trend comparison">
                <p className="panel-note">
                    Side-by-side champion and challenger values from persisted training artifacts.
                </p>
                <MetricCompareBars rows={compareRows} />
            </DataPanel>
        );
    }

    if (tab === 'scenario') {
        return (
            <DataPanel className="model-tab-panel" title="Scenario-family held-out lift">
                <p className="panel-note">
                    Realized markout lift (bps) on held-out toxic episodes. Preview fixtures until
                    Gold backfill is wired.
                </p>
                <ScenarioLiftBars rows={scenarioLiftSeries()} />
            </DataPanel>
        );
    }

    if (tab === 'threshold') {
        return (
            <DataPanel className="model-tab-panel" title="Quoting threshold analysis">
                <p className="panel-note">
                    Toxicity cutoff τ = {threshold.threshold.toFixed(2)} from benchmark policy (
                    {String(benchmark?.data.policy ?? 'widen/withhold when toxicity > tau')}).
                </p>
                <div className="threshold-grid">
                    <div>
                        <span>Champion precision @ τ</span>
                        <strong className="num">{threshold.activePrecision.toFixed(3)}</strong>
                        <ThresholdBar value={threshold.activePrecision} />
                        <small>FPR {threshold.activeFpr.toFixed(2)}</small>
                    </div>
                    <div>
                        <span>Challenger precision @ τ</span>
                        <strong className="num">{threshold.candidatePrecision.toFixed(3)}</strong>
                        <ThresholdBar value={threshold.candidatePrecision} />
                        <small>FPR {threshold.candidateFpr.toFixed(2)}</small>
                    </div>
                </div>
            </DataPanel>
        );
    }

    return (
        <DataPanel className="model-tab-panel" title="Calibration quality">
            <p className="panel-note">
                Isotonic calibration on walk-forward out-of-fold scores. Lower Brier is better.
            </p>
            <CalibrationCompare
                activeBrier={calibration.activeBrier}
                candidateBrier={calibration.candidateBrier}
                activePrAuc={calibration.activePrAuc}
                candidatePrAuc={calibration.candidatePrAuc}
            />
        </DataPanel>
    );
}
