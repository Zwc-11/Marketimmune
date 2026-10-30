import { useState } from 'react';
import { MarketHeader } from '../components/MarketHeader';
import { OrderBook } from '../components/OrderBook';
import { Panel, Tabs } from '../components/Panel';
import { ChartIntervals, PriceChart } from '../components/PriceChart';
import { QuoteGuard } from '../components/QuoteGuard';
import { RegretTape } from '../components/RegretTape';
import { ApiScoredFills, BackfillJobs, FoldsTable, RegretLog } from '../components/TerminalTables';
import { useMarket } from '../market/useMarket';

type BottomTab = 'log' | 'api' | 'folds' | 'backfills';

function ModelChip() {
    const model = useMarket((s) => s.model);
    const text =
        model.state === 'ready' ? 'Scoring live' : model.state === 'loading' ? 'Loading' : 'Labels only';
    return <span className={`chip ${model.state === 'ready' ? 'chip-live' : ''}`}>{text}</span>;
}

export default function TerminalPage() {
    const [tab, setTab] = useState<BottomTab>('log');
    return (
        <div className="terminal">
            <div className="area-head">
                <MarketHeader />
            </div>
            <Panel
                className="area-chart"
                title="Price"
                actions={
                    <>
                        <span className="faint chart-note">Dots mark withheld fills</span>
                        <ChartIntervals />
                    </>
                }
            >
                <PriceChart />
            </Panel>
            <div className="area-book">
                <Panel className="book-panel" title="Order book">
                    <OrderBook />
                </Panel>
                <Panel
                    className="tape-panel"
                    title="Fills"
                    actions={<span className="faint" title="Each bar fills over the 10 s label horizon">10 s regret clock</span>}
                >
                    <RegretTape />
                </Panel>
            </div>
            <Panel className="area-guard" title="Quote guard" actions={<ModelChip />}>
                <QuoteGuard />
            </Panel>
            <section className="panel area-bottom">
                <header className="panel-head">
                    <Tabs<BottomTab>
                        label="Terminal tables"
                        value={tab}
                        onChange={setTab}
                        tabs={[
                            { id: 'log', label: 'Regret log' },
                            { id: 'api', label: 'Scored Gold fills' },
                            { id: 'folds', label: 'Validation folds' },
                            { id: 'backfills', label: 'Backfill jobs' },
                        ]}
                    />
                </header>
                <div className="panel-body scroll" role="tabpanel">
                    {tab === 'log' && <RegretLog />}
                    {tab === 'api' && <ApiScoredFills />}
                    {tab === 'folds' && <FoldsTable />}
                    {tab === 'backfills' && <BackfillJobs />}
                </div>
            </section>
        </div>
    );
}
