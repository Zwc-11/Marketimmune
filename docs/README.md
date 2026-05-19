# MarketImmune Dashboard

Interactive visualization dashboard for the MarketImmune benchmark project.

## Overview

The dashboard provides a comprehensive view of:

- **Project Statistics**: Phases completed, benchmark examples, tasks, and models
- **Development Timeline**: Visual phase progression from 1-9
- **Benchmark Results**: Task metrics, data split distribution, model performance
- **Quality Gates**: Test coverage, type checking, and validation results
- **Model Leaderboard**: Ranked model performance across tasks
- **System Architecture**: Data pipeline, evaluation framework, and model implementations

## Features

- 📊 Interactive charts (PR-AUC, AUROC, F1, lead times)
- 🏆 Model leaderboard with rankings
- ✅ Quality gates and test results
- 🎯 Detailed phase-by-phase metrics
- 📈 Data distribution visualizations
- 🚀 Timeline and progress tracking

## Usage

### Local Viewing

Simply open `dashboard.html` in a web browser:

```bash
# Open directly
open docs/dashboard.html

# Or on Windows
start docs/dashboard.html
```

### Hosting

To serve the dashboard online:

1. **GitHub Pages**: Dashboard is already in `docs/` folder and can be served via GitHub Pages
2. **Web Server**: Copy to any web server (nginx, Apache, etc.)
3. **Local Server**: Use Python to serve locally:

```bash
python -m http.server 8000
# Navigate to http://localhost:8000/docs/dashboard.html
```

## Data Sources

The dashboard displays data from:

- `reports/phase7/benchmark_report.json` - Main benchmark results
- `reports/phase7/leaderboard.csv` - Model rankings
- `reports/phase8/metrics.json` - GRU-MTPP performance
- `reports/phase9/order_s2p2_metrics.json` - S2P2 Neural Hawkes performance
- Phase proof reports for quality gates

## Customization

To update metrics displayed in the dashboard:

1. Edit the `initCharts()` function to update chart data
2. Edit `populatePhase7Metrics()` to update task metrics
3. Edit `populateLeaderboard()` to update model rankings
4. Modify CSS color scheme in the `<style>` section

## Color Scheme

- **Primary Blue**: `#60a5fa` (Accent)
- **Emerald Green**: `#34d399` (Success/Positive)
- **Amber Yellow**: `#fbbf24` (Warning/Caution)
- **Dark Slate**: `#0f172a` (Background)

## Browser Support

Works on all modern browsers:
- Chrome/Edge (latest)
- Firefox (latest)
- Safari (latest)
- Mobile browsers (responsive design)

## License

Same as MarketImmune project.
