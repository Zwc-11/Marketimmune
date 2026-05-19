// dashboard.js — Plotly-powered advanced dashboard

/* ── Shared Plotly theme ───────────────────────────────────────────────── */
const THEME = {
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor:  'rgba(0,0,0,0)',
  font:  { family: 'system-ui, sans-serif', color: '#94a3b8', size: 12 },
  colorway: ['#38bdf8','#34d399','#818cf8','#fbbf24','#f87171','#fb923c'],
  gridcolor:  'rgba(148,163,184,.09)',
  zerolinecolor: 'rgba(148,163,184,.15)',
};

function applyTheme(layout) {
  return Object.assign({
    paper_bgcolor: THEME.paper_bgcolor,
    plot_bgcolor:  THEME.plot_bgcolor,
    font: THEME.font,
    colorway: THEME.colorway,
    margin: { t: 20, r: 16, b: 48, l: 52 },
  }, layout);
}

const CONFIG = { responsive: true, displayModeBar: false };

/* ── Task data ─────────────────────────────────────────────────────────── */
const TASKS = [
  { name: 'Event Detection',       prauc: 0.987, auroc: 0.834, f1: 0.900, latency: null,  status: 'Excellent' },
  { name: 'Session Class.',        prauc: 1.000, auroc: null,  f1: 0.907, latency: null,  status: 'Perfect'   },
  { name: 'Early Warning',         prauc: null,  auroc: null,  f1: null,  latency: 1030,  status: 'Good'      },
  { name: 'Harm Estimation',       prauc: null,  auroc: null,  f1: null,  latency: null,  status: 'Good'      },
  { name: 'Action Selection',      prauc: null,  auroc: null,  f1: null,  latency: null,  status: 'Monitor'   },
  { name: 'OOD Detection',         prauc: 0.576, auroc: 0.391, f1: null,  latency: null,  status: 'Monitor'   },
];

const MODELS = [
  { name: 'GRU-MTPP',  task: 'Event Detection',  prauc: 1.000, auroc: 1.000, latency: 1.235, rank: 1 },
  { name: 'S2P2-NHP',  task: 'Event Detection',  prauc: 1.000, auroc: 1.000, latency: 1.235, rank: 2 },
  { name: 'RuleEngine',task: 'Session Class.',    prauc: 1.000, auroc: null,  latency: 0.001, rank: 3 },
];

const PHASES = [
  { num: '1',   title: 'Schemas',    tests: 20,  features: 0,   examples: 0    },
  { num: '2',   title: 'Ingest',     tests: 35,  features: 0,   examples: 5000 },
  { num: '3',   title: 'Lake',       tests: 52,  features: 0,   examples: 8000 },
  { num: '4',   title: 'Replay',     tests: 75,  features: 12,  examples: 8000 },
  { num: '5',   title: 'Scenarios',  tests: 90,  features: 30,  examples: 12000},
  { num: '6',   title: 'Features',   tests: 109, features: 72,  examples: 15000},
  { num: '7',   title: 'AegisBench', tests: 120, features: 72,  examples: 18000},
  { num: '8',   title: 'GRU-MTPP',   tests: 135, features: 72,  examples: 18000},
  { num: '9',   title: 'S2P2',       tests: 152, features: 72,  examples: 18000},
];

/* ── Phase timeline pills ──────────────────────────────────────────────── */
function renderPhaseTimeline() {
  const container = document.getElementById('phases-timeline');
  if (!container) return;
  container.innerHTML = PHASES.map((p, i) => `
    <div class="phase-pill done glass p-3 rounded-xl text-center fade-up" style="animation-delay:${i * 0.05}s">
      <div class="phase-num text-xl font-black text-emerald-400 mb-0.5">${p.num}</div>
      <div class="text-xs font-semibold text-slate-300">${p.title}</div>
    </div>
  `).join('');
}

/* ── Metrics table ─────────────────────────────────────────────────────── */
function renderMetricsTable() {
  const tbody = document.getElementById('metrics-table');
  if (!tbody) return;

  const badgeClass = (s) => ({
    Perfect: 'badge-perfect', Excellent: 'badge-excel',
    Good: 'badge-good', Monitor: 'badge-monitor',
  }[s] || 'badge-monitor');

  const fmt = (v) => v == null ? '<span class="text-slate-600">—</span>'
    : `<span class="font-mono text-emerald-400">${v.toFixed(3)}</span>`;

  const bar = (v) => {
    const pct = v == null ? 0 : Math.round(v * 100);
    const color = pct >= 90 ? '#34d399' : pct >= 60 ? '#fbbf24' : '#f87171';
    return `
      <div class="flex items-center gap-2 justify-center">
        <div class="progress-track w-24">
          <div class="progress-fill" style="width:${pct}%;background:${color}"></div>
        </div>
        <span class="text-xs text-slate-500 w-8 text-right">${pct}%</span>
      </div>`;
  };

  const f1fmt = (t) => {
    if (t.f1 != null) return fmt(t.f1);
    if (t.latency != null) return `<span class="font-mono text-amber-400">${t.latency}ms</span>`;
    if (t.name === 'Harm Estimation') return `<span class="font-mono text-amber-400">MAE 0.249</span>`;
    if (t.name === 'Action Selection') return `<span class="font-mono text-amber-400">4333/100k</span>`;
    return '<span class="text-slate-600">—</span>';
  };

  tbody.innerHTML = TASKS.map((t, i) => `
    <tr class="metric-row border-b border-slate-800/60">
      <td class="px-5 py-3 text-slate-500 text-xs">${i + 1}</td>
      <td class="px-5 py-3 font-semibold text-slate-200 text-sm">${t.name}</td>
      <td class="px-5 py-3 text-right">${fmt(t.prauc)}</td>
      <td class="px-5 py-3 text-right">${fmt(t.auroc)}</td>
      <td class="px-5 py-3 text-right">${f1fmt(t)}</td>
      <td class="px-5 py-3">${bar(t.prauc)}</td>
      <td class="px-5 py-3 text-center"><span class="badge ${badgeClass(t.status)}">${t.status}</span></td>
    </tr>
  `).join('');
}

/* ── Leaderboard ───────────────────────────────────────────────────────── */
function renderLeaderboard() {
  const container = document.getElementById('leaderboard-container');
  if (!container) return;
  const medals = ['🥇', '🥈', '🥉'];
  const medalBg = [
    'rgba(251,191,36,.15)', 'rgba(203,213,225,.12)', 'rgba(251,146,60,.12)',
  ];
  container.innerHTML = MODELS.map((m, i) => `
    <div class="lb-row px-6 py-4 flex items-center gap-4">
      <div class="text-3xl w-12 text-center" style="filter:drop-shadow(0 0 8px ${medalBg[i]})">${medals[i]}</div>
      <div class="flex-1">
        <p class="font-bold text-slate-100 text-base">${m.name}</p>
        <p class="text-xs text-slate-500">${m.task} · Phase 7</p>
      </div>
      <div class="text-right mr-6">
        <p class="text-xs text-slate-500 mb-0.5">PR-AUC</p>
        <p class="text-2xl font-black text-emerald-400 font-mono">${m.prauc.toFixed(3)}</p>
      </div>
      <div class="text-right mr-6">
        <p class="text-xs text-slate-500 mb-0.5">AUROC</p>
        <p class="text-2xl font-black text-sky-400 font-mono">${m.auroc != null ? m.auroc.toFixed(3) : '—'}</p>
      </div>
      <div class="text-right">
        <p class="text-xs text-slate-500 mb-0.5">Latency</p>
        <p class="text-lg font-bold text-violet-400 font-mono">${m.latency.toFixed(3)}ms</p>
      </div>
    </div>
  `).join('');
}

/* ── Grouped bar — PR-AUC & AUROC ─────────────────────────────────────── */
function chartGroupedBar() {
  const labels = TASKS.map(t => t.name);
  const prauc  = TASKS.map(t => t.prauc ?? 0);
  const auroc  = TASKS.map(t => t.auroc ?? 0);

  Plotly.newPlot('chart-grouped-bar', [
    { name: 'PR-AUC', x: labels, y: prauc, type: 'bar',
      marker: { color: '#38bdf8', opacity: 0.85 },
      text: prauc.map(v => v > 0 ? v.toFixed(3) : '—'), textposition: 'outside',
      textfont: { size: 10, color: '#38bdf8' } },
    { name: 'AUROC',  x: labels, y: auroc, type: 'bar',
      marker: { color: '#34d399', opacity: 0.85 },
      text: auroc.map(v => v > 0 ? v.toFixed(3) : '—'), textposition: 'outside',
      textfont: { size: 10, color: '#34d399' } },
  ], applyTheme({
    barmode: 'group',
    bargap: 0.25,
    bargroupgap: 0.08,
    yaxis: { range: [0, 1.12], gridcolor: THEME.gridcolor, zerolinecolor: THEME.zerolinecolor, title: 'Score' },
    xaxis: { gridcolor: 'transparent', tickfont: { size: 10 } },
    legend: { orientation: 'h', y: -0.18, font: { size: 11 } },
    margin: { t: 24, r: 10, b: 80, l: 45 },
  }), CONFIG);
}

/* ── Radar chart ───────────────────────────────────────────────────────── */
function chartRadar() {
  const cats = ['PR-AUC', 'AUROC', 'F1', 'Lead-time', 'Precision', 'Recall'];
  const taskData = [
    { name: 'Event Det.',   r: [0.987, 0.834, 0.900, 0.0,  0.91, 0.89] },
    { name: 'Session Cls.', r: [1.000, 0.0,   0.907, 0.0,  1.0,  0.91] },
    { name: 'Early Warn.',  r: [0.0,   0.0,   0.0,   0.95, 0.88, 0.82] },
    { name: 'OOD Det.',     r: [0.576, 0.391, 0.0,   0.0,  0.58, 0.60] },
  ];
  const colors = ['#38bdf8','#34d399','#fbbf24','#f87171'];

  Plotly.newPlot('chart-radar',
    taskData.map((t, i) => ({
      type: 'scatterpolar',
      r: [...t.r, t.r[0]],
      theta: [...cats, cats[0]],
      fill: 'toself',
      name: t.name,
      line: { color: colors[i], width: 2 },
      fillcolor: colors[i].replace(')', ',.12)').replace('rgb', 'rgba'),
      opacity: 0.9,
    })),
    applyTheme({
      polar: {
        bgcolor: 'rgba(0,0,0,0)',
        radialaxis: { visible: true, range: [0, 1.05], gridcolor: THEME.gridcolor, tickfont: { size: 9 } },
        angularaxis: { gridcolor: THEME.gridcolor, tickfont: { size: 10 } },
      },
      legend: { orientation: 'h', y: -0.12, font: { size: 10 } },
      margin: { t: 16, r: 30, b: 60, l: 30 },
    }), CONFIG);
}

/* ── Heatmap ───────────────────────────────────────────────────────────── */
function chartHeatmap() {
  const tasks   = TASKS.map(t => t.name);
  const metrics = ['PR-AUC', 'AUROC', 'F1'];
  const z = [
    [0.987, 0.834, 0.900],
    [1.000, null,  0.907],
    [null,  null,  null ],
    [null,  null,  null ],
    [null,  null,  null ],
    [0.576, 0.391, null ],
  ].map(row => row.map(v => v ?? 0));

  const text = [
    ['0.987','0.834','0.900'],
    ['1.000','—',    '0.907'],
    ['—',    '—',    'Lead 1030ms'],
    ['—',    '—',    'MAE 0.249'],
    ['—',    '—',    '4333/100k'],
    ['0.576','0.391','—'],
  ];

  Plotly.newPlot('chart-heatmap', [{
    type: 'heatmap',
    z, x: metrics, y: tasks,
    text, texttemplate: '%{text}',
    textfont: { size: 11 },
    colorscale: [
      [0,   'rgba(15,23,42,1)'],
      [0.3, 'rgba(30,58,80,1)'],
      [0.6, 'rgba(8,122,145,1)'],
      [1,   'rgba(52,211,153,1)'],
    ],
    showscale: true,
    colorbar: { tickfont: { size: 9, color: '#94a3b8' }, len: 0.8 },
    hovertemplate: '<b>%{y}</b><br>%{x}: %{text}<extra></extra>',
  }], applyTheme({
    xaxis: { side: 'top', tickfont: { size: 11 } },
    yaxis: { autorange: 'reversed', tickfont: { size: 10 } },
    margin: { t: 40, r: 60, b: 10, l: 140 },
  }), CONFIG);
}

/* ── Sunburst ──────────────────────────────────────────────────────────── */
function chartSunburst() {
  Plotly.newPlot('chart-sunburst', [{
    type: 'sunburst',
    ids:    ['Dataset','Train','Val','Test',
             'Tr-ED','Tr-SC','Tr-EW','Tr-HE','Tr-AS','Tr-OD',
             'Va-ED','Va-SC','Va-EW',
             'Te-ED','Te-SC','Te-OOD'],
    labels: ['18K Examples','Train 61.5%','Val 19%','Test 19.5%',
             'Event Det.','Session','Early Warn.','Harm Est.','Action Sel.','OOD Det.',
             'Event Det.','Session','Early Warn.',
             'Event Det.','Session','OOD Det.'],
    parents:['','Dataset','Dataset','Dataset',
             'Train','Train','Train','Train','Train','Train',
             'Val','Val','Val',
             'Test','Test','Test'],
    values: [18000, 11070, 3420, 3510,
             1845, 1845, 1845, 1845, 1845, 1845,
             1140, 1140, 1140,
             1170, 1170, 1170],
    branchvalues: 'total',
    marker: { colors: ['#0f172a','#38bdf8','#818cf8','#34d399',
                        '#1e6a8a','#1a7a5e','#1d6b94','#1a7a5e','#165f6f','#0f5158',
                        '#4c3ea0','#3f3590','#3a3085',
                        '#1a8c60','#188053','#157346'] },
    hovertemplate: '<b>%{label}</b><br>%{value} examples<extra></extra>',
    textfont: { size: 10 },
  }], applyTheme({
    margin: { t: 0, r: 0, b: 0, l: 0 },
  }), CONFIG);
}

/* ── Scatter latency vs score ──────────────────────────────────────────── */
function chartScatter() {
  const latencies = [1.235, 1.235, 0.001];
  const praucs    = [1.000, 1.000, 1.000];
  const sizes     = [28, 24, 20];
  const names     = ['GRU-MTPP','S2P2-NHP','RuleEngine'];
  const colors    = ['#38bdf8','#818cf8','#34d399'];

  Plotly.newPlot('chart-scatter', [{
    type: 'scatter',
    mode: 'markers+text',
    x: latencies, y: praucs,
    text: names,
    textposition: 'top center',
    textfont: { size: 10 },
    marker: {
      size: sizes,
      color: colors,
      opacity: 0.85,
      line: { width: 1.5, color: '#1e293b' },
    },
    hovertemplate: '<b>%{text}</b><br>Latency: %{x:.3f}ms<br>PR-AUC: %{y:.3f}<extra></extra>',
  }], applyTheme({
    xaxis: {
      title: 'Inference Latency (ms)', gridcolor: THEME.gridcolor,
      zerolinecolor: THEME.zerolinecolor, type: 'log',
    },
    yaxis: { title: 'PR-AUC', range: [0.95, 1.02], gridcolor: THEME.gridcolor },
    margin: { t: 20, r: 20, b: 55, l: 55 },
  }), CONFIG);
}

/* ── Waterfall phase progress ──────────────────────────────────────────── */
function chartWaterfall() {
  const labels = PHASES.map(p => `Ph.${p.num}`);
  const tests  = PHASES.map(p => p.tests);

  Plotly.newPlot('chart-waterfall', [
    {
      name: 'Tests', x: labels, y: tests,
      type: 'bar',
      marker: {
        color: tests.map(v => `rgba(56,189,248,${0.4 + v / 200})`),
        line: { color: '#38bdf8', width: 1 },
      },
      text: tests.map(String), textposition: 'outside',
      textfont: { size: 9, color: '#38bdf8' },
    },
    {
      name: 'Features', x: labels, y: PHASES.map(p => p.features),
      type: 'scatter', mode: 'lines+markers',
      line: { color: '#34d399', width: 2 },
      marker: { size: 6, color: '#34d399' },
      yaxis: 'y2',
    },
  ], applyTheme({
    barmode: 'overlay',
    yaxis:  { title: 'Tests', gridcolor: THEME.gridcolor },
    yaxis2: { title: 'Features', overlaying: 'y', side: 'right',
              gridcolor: 'transparent', tickfont: { color: '#34d399', size: 10 } },
    xaxis:  { gridcolor: 'transparent' },
    legend: { orientation: 'h', y: -0.2, font: { size: 10 } },
    margin: { t: 20, r: 55, b: 70, l: 45 },
  }), CONFIG);
}

/* ── 3-D Scatter ───────────────────────────────────────────────────────── */
function chart3dScatter() {
  const prauc  = [0.987, 1.000, 0,     0,     0,     0.576];
  const auroc  = [0.834, 0,     0,     0,     0,     0.391];
  const f1     = [0.900, 0.907, 0,     0,     0,     0    ];
  const labels = TASKS.map(t => t.name);
  const colors = ['#38bdf8','#34d399','#fbbf24','#fb923c','#f87171','#818cf8'];

  Plotly.newPlot('chart-3d-scatter', [{
    type: 'scatter3d',
    mode: 'markers+text',
    x: prauc, y: auroc, z: f1,
    text: labels,
    textposition: 'top center',
    textfont: { size: 9 },
    marker: {
      size: 10,
      color: colors,
      opacity: 0.88,
      line: { color: '#0f172a', width: 1 },
    },
    hovertemplate: '<b>%{text}</b><br>PR-AUC: %{x:.3f}<br>AUROC: %{y:.3f}<br>F1: %{z:.3f}<extra></extra>',
  }], applyTheme({
    scene: {
      xaxis: { title: 'PR-AUC', gridcolor: THEME.gridcolor, backgroundcolor: 'rgba(0,0,0,0)', showbackground: false },
      yaxis: { title: 'AUROC',  gridcolor: THEME.gridcolor, backgroundcolor: 'rgba(0,0,0,0)', showbackground: false },
      zaxis: { title: 'F1',     gridcolor: THEME.gridcolor, backgroundcolor: 'rgba(0,0,0,0)', showbackground: false },
      bgcolor: 'rgba(0,0,0,0)',
      camera: { eye: { x: 1.6, y: 1.6, z: 0.9 } },
    },
    margin: { t: 0, r: 0, b: 0, l: 0 },
  }), CONFIG);
}

/* ── 3-D Surface ───────────────────────────────────────────────────────── */
function chart3dSurface() {
  const n = 30;
  const xs = Array.from({ length: n }, (_, i) => i / (n - 1));
  const ys = Array.from({ length: n }, (_, i) => i / (n - 1));
  const z  = ys.map(y => xs.map(x => {
    // Simulated score landscape: peak at high PR-AUC & AUROC
    const base = Math.pow(x, 0.6) * Math.pow(y + 0.2, 0.5);
    const noise = (Math.sin(x * 8) * Math.cos(y * 6)) * 0.04;
    return Math.min(1, Math.max(0, base + noise));
  }));

  Plotly.newPlot('chart-3d-surface', [{
    type: 'surface',
    x: xs, y: ys, z,
    colorscale: [
      [0,    '#0f172a'],
      [0.25, '#1e3a5f'],
      [0.5,  '#0e7490'],
      [0.75, '#0891b2'],
      [1,    '#34d399'],
    ],
    opacity: 0.9,
    contours: {
      z: { show: true, usecolormap: true, highlightcolor: '#38bdf8', project: { z: true } },
    },
    colorbar: { tickfont: { size: 9, color: '#94a3b8' }, len: 0.7 },
    hovertemplate: 'PR-AUC: %{x:.2f}<br>AUROC: %{y:.2f}<br>Score: %{z:.3f}<extra></extra>',
  }], applyTheme({
    scene: {
      xaxis: { title: 'PR-AUC', backgroundcolor: 'rgba(0,0,0,0)', showbackground: false, gridcolor: THEME.gridcolor },
      yaxis: { title: 'AUROC',  backgroundcolor: 'rgba(0,0,0,0)', showbackground: false, gridcolor: THEME.gridcolor },
      zaxis: { title: 'Score',  backgroundcolor: 'rgba(0,0,0,0)', showbackground: false, gridcolor: THEME.gridcolor },
      bgcolor: 'rgba(0,0,0,0)',
      camera: { eye: { x: 1.7, y: -1.5, z: 1.1 } },
    },
    margin: { t: 0, r: 0, b: 0, l: 0 },
  }), CONFIG);
}

/* ── Parallel coordinates ──────────────────────────────────────────────── */
function chartParallel() {
  // Map status to numeric tier for color
  const statusMap = { Perfect: 4, Excellent: 3, Good: 2, Monitor: 1 };
  const prauc  = TASKS.map(t => t.prauc  ?? 0);
  const auroc  = TASKS.map(t => t.auroc  ?? 0);
  const f1vals = TASKS.map(t => t.f1     ?? 0);
  const tier   = TASKS.map(t => statusMap[t.status] ?? 1);

  Plotly.newPlot('chart-parallel', [{
    type: 'parcoords',
    line: {
      color: tier,
      colorscale: [
        [0,    '#f87171'],
        [0.33, '#fbbf24'],
        [0.66, '#38bdf8'],
        [1,    '#34d399'],
      ],
      showscale: true,
      colorbar: {
        title: 'Tier',
        tickvals: [1, 2, 3, 4],
        ticktext: ['Monitor','Good','Excellent','Perfect'],
        tickfont: { size: 9, color: '#94a3b8' },
        len: 0.7,
      },
    },
    dimensions: [
      { label: 'PR-AUC',  values: prauc,  range: [0, 1] },
      { label: 'AUROC',   values: auroc,  range: [0, 1] },
      { label: 'F1',      values: f1vals, range: [0, 1] },
      { label: 'Status',  values: tier,   range: [1, 4],
        tickvals: [1, 2, 3, 4], ticktext: ['Monitor','Good','Excel.','Perfect'] },
    ],
    labelangle: 0,
    labelside: 'top',
  }], applyTheme({
    margin: { t: 60, r: 80, b: 30, l: 60 },
  }), CONFIG);
}

/* ── Phase coverage area chart ─────────────────────────────────────────── */
function chartCoverage() {
  const labels = PHASES.map(p => `Phase ${p.num}`);
  const tests  = PHASES.map(p => p.tests);
  const examples = PHASES.map(p => p.examples / 1000);

  Plotly.newPlot('chart-coverage', [
    {
      name: 'Tests passing',
      x: labels, y: tests,
      type: 'scatter', mode: 'lines+markers',
      fill: 'tozeroy',
      line: { color: '#38bdf8', width: 2.5 },
      marker: { size: 7, color: '#38bdf8' },
      fillcolor: 'rgba(56,189,248,.1)',
      hovertemplate: '%{x}<br>Tests: %{y}<extra></extra>',
    },
    {
      name: 'Examples (K)',
      x: labels, y: examples,
      type: 'scatter', mode: 'lines+markers',
      fill: 'tozeroy',
      line: { color: '#34d399', width: 2.5, dash: 'dot' },
      marker: { size: 7, color: '#34d399' },
      fillcolor: 'rgba(52,211,153,.07)',
      yaxis: 'y2',
      hovertemplate: '%{x}<br>Examples: %{y}K<extra></extra>',
    },
  ], applyTheme({
    yaxis:  { title: 'Tests', gridcolor: THEME.gridcolor, zerolinecolor: THEME.zerolinecolor },
    yaxis2: { title: 'Examples (K)', overlaying: 'y', side: 'right',
              gridcolor: 'transparent', tickfont: { color: '#34d399', size: 10 } },
    xaxis:  { gridcolor: THEME.gridcolor },
    legend: { orientation: 'h', y: -0.18, font: { size: 11 } },
    margin: { t: 16, r: 55, b: 65, l: 50 },
  }), CONFIG);
}

/* ── Stats from API ────────────────────────────────────────────────────── */
async function loadStats() {
  try {
    const res  = await fetch('/api/summary/');
    if (!res.ok) return;
    const data = await res.json();
    const s    = data.stats;
    const ph   = document.getElementById('stat-phases');
    const ex   = document.getElementById('stat-examples');
    const ta   = document.getElementById('stat-tasks');
    const mo   = document.getElementById('stat-models');
    if (ph) ph.textContent = s.total_phases;
    if (ex) ex.textContent = `${Math.round(s.total_examples / 1000)}K+`;
    if (ta) ta.textContent = s.total_tasks;
    if (mo) mo.textContent = s.total_models;
  } catch (_) { /* use defaults */ }
}

/* ── Boot ──────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  loadStats();
  renderPhaseTimeline();
  renderMetricsTable();
  renderLeaderboard();

  // Defer charts until layout is ready
  requestAnimationFrame(() => {
    chartGroupedBar();
    chartRadar();
    chartHeatmap();
    chartSunburst();
    chartScatter();
    chartWaterfall();
    chart3dScatter();
    chart3dSurface();
    chartParallel();
    chartCoverage();
  });
});
