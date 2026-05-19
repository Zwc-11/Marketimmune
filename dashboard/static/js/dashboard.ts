// dashboard.ts - TypeScript source file for dashboard

interface TaskMetric {
  id: number;
  task_name: string;
  task_display: string;
  pr_auc: number | null;
  auroc: number | null;
  f1_score: number | null;
  other_metrics: Record<string, any>;
  status: string;
  phase: number;
}

interface ModelMetric {
  id: number;
  model_name: string;
  model_display: string;
  task_name: string;
  pr_auc: number;
  auroc: number | null;
  inference_latency_ms: number | null;
  extra_metrics: Record<string, any>;
  phase: number;
  rank: number;
}

interface ProjectStats {
  total_examples: number;
  total_tasks: number;
  total_phases: number;
  total_models: number;
  test_coverage: number;
  type_errors: number;
  linting_violations: number;
  test_count: number;
  last_updated: string;
}

interface DashboardData {
  stats: ProjectStats;
  task_metrics: TaskMetric[];
  model_metrics: ModelMetric[];
}

class Dashboard {
  private apiBaseUrl: string = '/api';
  private taskMetricsChart: Chart | null = null;
  private splitChart: Chart | null = null;
  private eventDetectionChart: Chart | null = null;
  private modelComparisonChart: Chart | null = null;
  private data: DashboardData | null = null;

  constructor() {
    this.init();
  }

  async init(): Promise<void> {
    try {
      await this.loadData();
      this.renderStats();
      this.renderPhaseTimeline();
      this.renderMetricsTable();
      this.renderLeaderboard();
      this.initCharts();
    } catch (error) {
      console.error('Failed to initialize dashboard:', error);
      this.showError('Failed to load dashboard data');
    }
  }

  private async loadData(): Promise<void> {
    const response = await fetch(`${this.apiBaseUrl}/summary/`);
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    this.data = await response.json();
  }

  private renderStats(): void {
    if (!this.data) return;

    const stats = this.data.stats;
    document.getElementById('stat-phases')!.textContent = stats.total_phases.toString();
    document.getElementById('stat-examples')!.textContent = `${(stats.total_examples / 1000).toFixed(0)}K+`;
    document.getElementById('stat-tasks')!.textContent = stats.total_tasks.toString();
    document.getElementById('stat-models')!.textContent = stats.total_models.toString();
  }

  private renderPhaseTimeline(): void {
    const phases = [
      { num: '1-3', title: 'Foundation', desc: 'Schemas & CI' },
      { num: '4', title: 'Replay', desc: 'Deterministic' },
      { num: '5', title: 'Scenarios', desc: 'Generation' },
      { num: '6', title: 'Features', desc: 'Rules' },
      { num: '7', title: 'AegisBench', desc: 'Benchmark' },
      { num: '8', title: 'GRU-MTPP', desc: 'Baseline' },
      { num: '9', title: 'S2P2', desc: 'Neural Hawkes' },
    ];

    const timeline = document.getElementById('phases-timeline')!;
    timeline.innerHTML = phases.map((p, i) => `
      <div class="phase-pill glass-effect p-4 rounded-lg text-center hover:border-blue-400 transition cursor-pointer" 
           style="animation-delay: ${i * 0.05}s" class="fade-in">
        <div class="text-2xl font-bold gradient-text mb-2">${p.num}</div>
        <div class="text-xs font-semibold uppercase">${p.title}</div>
        <div class="text-xs text-slate-500">${p.desc}</div>
      </div>
    `).join('');
  }

  private renderMetricsTable(): void {
    if (!this.data) return;

    const metricsData = [
      {
        task: 'Event Detection',
        prauc: '0.987',
        auroc: '0.834',
        f1: '0.900',
        status: 'Excellent',
      },
      {
        task: 'Session Classification',
        prauc: '1.000',
        auroc: '—',
        f1: '0.907',
        status: 'Perfect',
      },
      {
        task: 'Early Warning',
        prauc: '—',
        auroc: '—',
        f1: 'Lead: 1030ms',
        status: 'Good',
      },
      {
        task: 'Harm Estimation',
        prauc: '—',
        auroc: '—',
        f1: 'MAE: 0.249',
        status: 'Good',
      },
      {
        task: 'Action Selection',
        prauc: '—',
        auroc: '—',
        f1: '4333/100k',
        status: 'Monitor',
      },
      {
        task: 'OOD Detection',
        prauc: '0.576',
        auroc: '0.391',
        f1: '—',
        status: 'Monitor',
      },
    ];

    const tbody = document.getElementById('metrics-table')!;
    tbody.innerHTML = metricsData.map(m => `
      <tr class="hover:bg-slate-800/50 transition">
        <td class="px-6 py-4 text-sm font-semibold">${m.task}</td>
        <td class="px-6 py-4 text-sm font-mono text-emerald-400">${m.prauc}</td>
        <td class="px-6 py-4 text-sm font-mono text-emerald-400">${m.auroc}</td>
        <td class="px-6 py-4 text-sm font-mono text-emerald-400">${m.f1}</td>
        <td class="px-6 py-4">
          <span class="metric-badge ${m.status === 'Perfect' || m.status === 'Excellent' ? 'badge-success' : 'badge-warning'}">
            ${m.status}
          </span>
        </td>
      </tr>
    `).join('');
  }

  private renderLeaderboard(): void {
    const leaderboardData = [
      { model: 'S2P2-NHP', task: 'Event Detection', score: '1.000', rank: 1 },
      { model: 'GRU-MTPP', task: 'Event Detection', score: '1.000', rank: 2 },
      { model: 'RuleEngine', task: 'Session Classification', score: '1.000', rank: 3 },
    ];

    const container = document.getElementById('leaderboard-container')!;
    container.innerHTML = leaderboardData.map((item, idx) => {
      let medalClass = '';
      let medal = '';
      if (idx === 0) {
        medalClass = 'medal-gold';
        medal = '🥇';
      } else if (idx === 1) {
        medalClass = 'medal-silver';
        medal = '🥈';
      } else if (idx === 2) {
        medalClass = 'medal-bronze';
        medal = '🥉';
      }

      return `
        <div class="flex items-center justify-between p-6 border-b border-slate-700 last:border-b-0 hover:bg-slate-800/30 transition">
          <div class="flex items-center gap-4 flex-1">
            <div class="leaderboard-medal ${medalClass}">${medal}</div>
            <div>
              <p class="font-semibold text-white">${item.model}</p>
              <p class="text-sm text-slate-400">${item.task}</p>
            </div>
          </div>
          <div class="text-right">
            <p class="text-2xl font-bold text-emerald-400 font-mono">${item.score}</p>
            <p class="text-xs text-slate-500">Rank #${item.rank}</p>
          </div>
        </div>
      `;
    }).join('');
  }

  private initCharts(): void {
    this.createTaskMetricsChart();
    this.createSplitChart();
    this.createEventDetectionChart();
    this.createModelComparisonChart();
  }

  private createTaskMetricsChart(): void {
    const ctx = (document.getElementById('taskMetricsChart') as HTMLCanvasElement).getContext('2d');
    if (!ctx) return;

    this.taskMetricsChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: ['Event\nDetection', 'Session\nClass', 'Early\nWarning', 'Harm\nEst', 'Action\nSel', 'OOD\nDet'],
        datasets: [
          {
            label: 'PR-AUC',
            data: [0.987, 1.0, 0.85, 0.65, 0.70, 0.576],
            backgroundColor: ['#3b82f6', '#10b981', '#f59e0b', '#fb923c', '#ec4899', '#a78bfa'],
            borderRadius: 6,
            borderSkipped: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
        },
        scales: {
          y: {
            beginAtZero: true,
            max: 1.0,
            ticks: { color: '#94a3b8' },
            grid: { color: 'rgba(148, 163, 184, 0.1)' },
          },
          x: {
            ticks: { color: '#94a3b8' },
            grid: { display: false },
          },
        },
      },
    });
  }

  private createSplitChart(): void {
    const ctx = (document.getElementById('splitChart') as HTMLCanvasElement).getContext('2d');
    if (!ctx) return;

    this.splitChart = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: ['Train (61.5%)', 'Validation (19%)', 'Test (19.5%)'],
        datasets: [
          {
            data: [11070, 3420, 3510],
            backgroundColor: ['#3b82f6', '#10b981', '#f59e0b'],
            borderColor: '#1e293b',
            borderWidth: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'bottom',
            labels: { color: '#cbd5e1', padding: 15 },
          },
        },
      },
    });
  }

  private createEventDetectionChart(): void {
    const ctx = (document.getElementById('eventDetectionChart') as HTMLCanvasElement).getContext('2d');
    if (!ctx) return;

    this.eventDetectionChart = new Chart(ctx, {
      type: 'radar',
      data: {
        labels: ['PR-AUC', 'AUROC', 'F1', 'P@10'],
        datasets: [
          {
            label: 'Event Detection',
            data: [98.7, 83.4, 90.0, 100],
            borderColor: '#3b82f6',
            backgroundColor: 'rgba(59, 130, 246, 0.1)',
            borderWidth: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: '#cbd5e1' } },
        },
        scales: {
          r: {
            ticks: { color: '#94a3b8' },
            grid: { color: 'rgba(148, 163, 184, 0.1)' },
            max: 100,
          },
        },
      },
    });
  }

  private createModelComparisonChart(): void {
    const ctx = (document.getElementById('modelComparisonChart') as HTMLCanvasElement).getContext('2d');
    if (!ctx) return;

    this.modelComparisonChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: ['GRU-MTPP', 'S2P2-NHP'],
        datasets: [
          {
            label: 'PR-AUC',
            data: [1.0, 1.0],
            backgroundColor: '#3b82f6',
            borderRadius: 6,
          },
          {
            label: 'AUROC',
            data: [1.0, 1.0],
            backgroundColor: '#10b981',
            borderRadius: 6,
          },
          {
            label: 'Lead Time (s)',
            data: [1.235, 1.235],
            backgroundColor: '#f59e0b',
            borderRadius: 6,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            labels: { color: '#cbd5e1', padding: 15 },
          },
        },
        scales: {
          y: {
            ticks: { color: '#94a3b8' },
            grid: { color: 'rgba(148, 163, 184, 0.1)' },
          },
          x: {
            ticks: { color: '#94a3b8' },
            grid: { display: false },
          },
        },
      },
    });
  }

  private showError(message: string): void {
    console.error(message);
    // You could add a proper error notification here
  }
}

// Initialize dashboard when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  new Dashboard();
});
