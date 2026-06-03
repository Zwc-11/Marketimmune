import { useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import type { ProductData } from '../routes';
import { Icon } from '../components/Icon';
import {
    CheckLine,
    DataPanel,
    EmptyState,
    FilterLine,
    LoadingState,
    PageHeader,
} from '../components/ui';
import { MemoryCard } from '../components/memory';
import {
    memoryCards,
    memoryMatchesType,
    memoryTypeCounts,
    noveltyBucket,
    recommendedDetectorRate,
    type MemoryTypeFilter,
    type NoveltyFilter,
} from '../lib/derive';

function toggleNoveltyFilter(
    filter: NoveltyFilter,
    setFilters: Dispatch<SetStateAction<Set<NoveltyFilter>>>,
) {
    setFilters((current) => {
        const next = new Set(current);
        if (next.has(filter) && next.size > 1) next.delete(filter);
        else next.add(filter);
        return next;
    });
}

export function MemoryLibraryScreen({
    data,
    loading,
}: {
    data: ProductData;
    loading: boolean;
}) {
    const realMemories = data.loopState?.memories ?? [];
    const [query, setQuery] = useState('');
    const [sortNewest, setSortNewest] = useState(true);
    const [activeType, setActiveType] = useState<MemoryTypeFilter>('all');
    const [noveltyFilters, setNoveltyFilters] = useState<Set<NoveltyFilter>>(
        () => new Set(['high', 'medium', 'low']),
    );
    const memories = memoryCards(realMemories)
        .filter((memory) => {
            const text =
                `${memory.threat_name} ${memory.description} ${memory.key_signals.join(' ')}`.toLowerCase();
            return text.includes(query.trim().toLowerCase());
        })
        .filter((memory) => activeType === 'all' || memoryMatchesType(memory, activeType))
        .filter((memory) => noveltyFilters.has(noveltyBucket(memory.novelty_score)))
        .sort((a, b) =>
            sortNewest ? b.times_seen - a.times_seen : a.threat_name.localeCompare(b.threat_name),
        );
    const typeCounts = memoryTypeCounts(realMemories);

    if (loading && realMemories.length === 0) {
        return <LoadingState label="Loading immune memory library" />;
    }

    return (
        <section className="screen-stack">
            <PageHeader
                title="Immune Memory Library"
                subtitle="Adverse-selection episodes the system has learned from."
                right={
                    <>
                        <label className="search-box">
                            <Icon name="search" />{' '}
                            <input
                                value={query}
                                onChange={(event) => setQuery(event.target.value)}
                                placeholder="Search memories..."
                            />
                        </label>
                        <button
                            className="outline-action"
                            type="button"
                            onClick={() => setQuery('')}
                        >
                            <Icon name="filter" /> Clear
                        </button>
                        <button
                            className="outline-action"
                            type="button"
                            onClick={() => setSortNewest((value) => !value)}
                        >
                            {sortNewest ? 'Most Seen' : 'A-Z'} <Icon name="chevron" />
                        </button>
                    </>
                }
            />
            <div className="memory-layout">
                <DataPanel className="memory-filter">
                    <strong>Memory Types</strong>
                    <FilterLine
                        icon="globe"
                        label="All Memories"
                        value={realMemories.length}
                        active={activeType === 'all'}
                        onClick={() => setActiveType('all')}
                    />
                    <FilterLine
                        icon="target"
                        label="Liquidation"
                        value={typeCounts.liquidation}
                        active={activeType === 'liquidation'}
                        onClick={() => setActiveType('liquidation')}
                    />
                    <FilterLine
                        icon="loop"
                        label="Basis Dislocation"
                        value={typeCounts.basis}
                        active={activeType === 'basis'}
                        onClick={() => setActiveType('basis')}
                    />
                    <FilterLine
                        icon="pulse"
                        label="Funding"
                        value={typeCounts.funding}
                        active={activeType === 'funding'}
                        onClick={() => setActiveType('funding')}
                    />
                    <FilterLine
                        icon="trend"
                        label="Momentum"
                        value={typeCounts.momentum}
                        active={activeType === 'momentum'}
                        onClick={() => setActiveType('momentum')}
                    />
                    <FilterLine
                        icon="layers"
                        label="Iceberg"
                        value={typeCounts.iceberg}
                        active={activeType === 'iceberg'}
                        onClick={() => setActiveType('iceberg')}
                    />
                    <FilterLine
                        icon="clock"
                        label="Other"
                        value={typeCounts.other}
                        active={activeType === 'other'}
                        onClick={() => setActiveType('other')}
                    />
                    <hr />
                    <strong>Novelty Score</strong>
                    <CheckLine
                        label="High (0.66 - 1.00)"
                        value={realMemories.filter((m) => m.novelty_score >= 0.66).length}
                        checked={noveltyFilters.has('high')}
                        onChange={() => toggleNoveltyFilter('high', setNoveltyFilters)}
                    />
                    <CheckLine
                        label="Medium (0.33 - 0.65)"
                        value={
                            realMemories.filter(
                                (m) => m.novelty_score >= 0.33 && m.novelty_score < 0.66,
                            ).length
                        }
                        checked={noveltyFilters.has('medium')}
                        onChange={() => toggleNoveltyFilter('medium', setNoveltyFilters)}
                    />
                    <CheckLine
                        label="Low (0.00 - 0.32)"
                        value={realMemories.filter((m) => m.novelty_score < 0.33).length}
                        checked={noveltyFilters.has('low')}
                        onChange={() => toggleNoveltyFilter('low', setNoveltyFilters)}
                    />
                    <hr />
                    <strong>First Seen</strong>
                    <button
                        className="outline-action full"
                        type="button"
                        onClick={() => setSortNewest((value) => !value)}
                    >
                        <Icon name="calendar" /> Toggle sort <Icon name="chevron" />
                    </button>
                </DataPanel>
                <div className="memory-main">
                    <div className="memory-count">
                        {memories.length} of {realMemories.length} memories
                    </div>
                    <div className="memory-card-grid">
                        {memories.length ? (
                            memories.map((memory, index) => (
                                <MemoryCard
                                    key={`${memory.threat_name}-${index}`}
                                    memory={memory}
                                    index={index}
                                />
                            ))
                        ) : (
                            <EmptyState
                                title="No memories found"
                                body="No persisted immune memories match the current filter."
                            />
                        )}
                    </div>
                </div>
            </div>
            <DataPanel className="insight-strip">
                <div>
                    <Icon name="brain" />
                    <strong>System Insight</strong>
                    <span>
                        {realMemories.length
                            ? `${realMemories.filter((memory) => memory.novelty_score >= 0.66).length} high-novelty memories persisted.`
                            : 'No persisted memory insights yet.'}
                    </span>
                </div>
                <div>
                    <strong>Top Learning</strong>
                    <span>
                        {realMemories[0]?.threat_name ?? 'Unavailable until memories are persisted.'}
                    </span>
                </div>
                <div>
                    <strong>Library Health</strong>
                    <span>
                        {realMemories.length} memories - {recommendedDetectorRate(realMemories)}{' '}
                        with recommended detector
                    </span>
                </div>
                <Icon name="chevron" />
            </DataPanel>
        </section>
    );
}
