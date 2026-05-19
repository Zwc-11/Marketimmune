# MarketImmune Dashboard

A modern, interactive web dashboard for visualizing MarketImmune benchmark results, built with Django, Django REST Framework, Chart.js, and Tailwind CSS.

## Features

- **Interactive Dashboards**: Real-time visualization of benchmark metrics across all 9 phases
- **Task Metrics**: Detailed performance metrics (PR-AUC, AUROC, F1) for 6 evaluation tasks
- **Model Leaderboard**: Rankings of neural baseline models with performance comparison
- **Phase Timeline**: Visual timeline showing all development phases
- **Quality Gates**: Code coverage, test counts, type checking status
- **API Endpoints**: RESTful API for programmatic access to all benchmark data
- **Modern UI**: Glassmorphism design with Tailwind CSS, dark theme with gradient accents

## Tech Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Backend | Django | 4.2.0 |
| API | Django REST Framework | 3.14.0 |
| Database | SQLite | 3+ |
| Frontend | HTML + JavaScript/TypeScript | ES6+ |
| Styling | Tailwind CSS | 3.0+ |
| Charts | Chart.js | 4.4.0 |
| Icons | Font Awesome | 6.4.0 |

## Project Structure

```
dashboard/
├── management/
│   └── commands/
│       └── load_metrics.py         # Django command to load benchmark data
├── migrations/                      # Database schema migrations
├── static/
│   └── js/
│       ├── dashboard.ts            # TypeScript source (optional)
│       └── dashboard.js            # Compiled JavaScript dashboard logic
├── templates/
│   └── dashboard/
│       └── index.html              # Main dashboard template
├── models.py                        # Database models (BenchmarkMetrics, TaskMetric, etc.)
├── serializers.py                   # DRF serializers for API
├── views.py                         # API endpoints and page views
├── urls.py                          # App-level URL routing
├── apps.py                          # Django app configuration
├── admin.py                         # Django admin interface
├── tests.py                         # Unit tests
└── requirements.txt                 # Python dependencies

dashboard_project/
├── settings.py                      # Django configuration
├── urls.py                          # Project-level URL routing
├── asgi.py                          # ASGI application
├── wsgi.py                          # WSGI application
└── manage.py                        # Django CLI

docs/
└── DASHBOARD_SETUP.md              # Detailed setup instructions
```

## Quick Start

### Prerequisites
- Python 3.8+
- pip or conda
- Git

### Installation

1. **Clone the repository** (if not already done):
   ```bash
   git clone https://github.com/Zwc-11/marketimmune-benchmark.git
   cd marketimmune-benchmark
   ```

2. **Create virtual environment**:
   ```bash
   python -m venv venv
   # On Windows
   venv\Scripts\activate
   # On macOS/Linux
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r dashboard/requirements.txt
   ```

4. **Apply migrations**:
   ```bash
   python manage.py migrate
   ```

5. **Load benchmark data**:
   ```bash
   python manage.py load_metrics
   ```

6. **Collect static files** (for production):
   ```bash
   python manage.py collectstatic --noinput
   ```

### Running the Dashboard

**Development server**:
```bash
python manage.py runserver
# Dashboard available at http://localhost:8000
```

**Production with Gunicorn**:
```bash
gunicorn dashboard_project.wsgi:application --bind 0.0.0.0:8000
```

## API Documentation

### REST Endpoints

All endpoints return JSON and support filtering/pagination:

#### Dashboard Overview
- `GET /` - Main dashboard page (HTML)
- `GET /api/summary/` - Complete dashboard summary (stats + tasks + models)
- `GET /api/stats/` - Project statistics (coverage, test count, etc.)

#### Leaderboard & Rankings
- `GET /api/leaderboard/` - Model leaderboard sorted by rank
- `GET /api/phase/<phase_id>/` - Metrics for specific phase

#### Data Collections
- `GET /api/task-metrics/` - All task metrics (paginated)
- `GET /api/model-metrics/` - All model metrics (paginated)
- `GET /api/benchmark-metrics/` - All benchmark phases (paginated)

### Example API Request

```bash
# Get dashboard summary
curl http://localhost:8000/api/summary/

# Get event detection task metrics
curl http://localhost:8000/api/task-metrics/?search=event_detection

# Get Phase 7 details
curl http://localhost:8000/api/phase/7/
```

### Response Format

```json
{
  "stats": {
    "total_examples": 18000,
    "total_tasks": 6,
    "test_coverage": 100.0,
    "last_updated": "2026-01-15T10:30:00Z"
  },
  "task_metrics": [
    {
      "id": 1,
      "task_name": "event_detection",
      "task_display": "Event Detection",
      "pr_auc": 0.987,
      "auroc": 0.834,
      "f1_score": 0.900,
      "status": "active"
    }
  ]
}
```

## Database Models

### BenchmarkMetrics
Stores metadata for each development phase:
- `phase` (INT, unique) - Phase number 1-9
- `title` (CharField) - Phase title
- `data` (JSONField) - Phase-specific metadata

### TaskMetric
Evaluation results for each task:
- `task_name` (CharField, choices) - One of 6 tasks
- `pr_auc` / `auroc` / `f1_score` (FloatField) - Performance metrics
- `other_metrics` (JSONField) - Additional metrics
- `status` (CharField) - Active/inactive
- `phase` (IntegerField) - Associated phase

### ModelMetric
Neural baseline performance:
- `model_name` (CharField, choices) - Model identifier
- `task_name` (CharField) - Target task
- `pr_auc` / `auroc` (FloatField) - Metrics
- `inference_latency_ms` (FloatField) - Latency in milliseconds
- `rank` (IntegerField) - Leaderboard ranking
- `phase` (IntegerField) - Development phase

### ProjectStats
Overall project statistics:
- `total_examples` (IntegerField) - Dataset size
- `total_tasks` (IntegerField) - Number of tasks
- `test_coverage` (FloatField) - Code coverage %
- `type_errors` (IntegerField) - Type checking errors
- `test_count` (IntegerField) - Passing tests

## Customization

### Styling
The dashboard uses Tailwind CSS for styling. Customize the UI by:
1. Editing [dashboard/templates/dashboard/index.html](dashboard/templates/dashboard/index.html)
2. Adding custom CSS in the `<style>` block
3. Modifying Tailwind classes directly in HTML

### Charts
Chart configurations are in [dashboard/static/js/dashboard.js](dashboard/static/js/dashboard.js):
- Modify chart types (bar, doughnut, radar, line)
- Change colors by editing `backgroundColor` properties
- Update data labels and datasets

### Data Loading
To add custom benchmark data:
1. Edit [dashboard/management/commands/load_metrics.py](dashboard/management/commands/load_metrics.py)
2. Add new BenchmarkMetrics, TaskMetric, or ModelMetric entries
3. Run `python manage.py load_metrics` again

## Configuration

### Environment Variables
Create `.env` file in project root:
```bash
DEBUG=True
SECRET_KEY=your-secret-key
ALLOWED_HOSTS=localhost,127.0.0.1,yourdomain.com
DATABASE_URL=sqlite:///db.sqlite3
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8000
```

### CORS Settings
Modify [dashboard_project/settings.py](dashboard_project/settings.py):
```python
CORS_ALLOWED_ORIGINS = [
    'http://localhost:3000',
    'http://localhost:8000',
    'https://yourdomain.com',
]
```

## Troubleshooting

### Dashboard not loading?
```bash
# Ensure migrations applied
python manage.py migrate

# Check static files collected
python manage.py collectstatic --noinput

# Verify URLs configured
python manage.py show_urls | grep dashboard
```

### API returns 404?
```bash
# Check database populated
python manage.py load_metrics

# Query test data
python manage.py shell
>>> from dashboard.models import ProjectStats
>>> ProjectStats.objects.all()
```

### CORS errors?
```python
# Update settings.py CORS configuration
CORS_ALLOWED_ORIGINS = ['http://yourfrontend:port']
```

## Development

### TypeScript Support (Optional)
To use TypeScript instead of JavaScript:

1. Install TypeScript:
   ```bash
   npm install -g typescript
   npm init -y
   npm install chart.js axios typescript
   ```

2. Create `tsconfig.json`:
   ```json
   {
     "compilerOptions": {
       "target": "ES6",
       "module": "ES6",
       "outDir": "dashboard/static/js",
       "strict": true
     }
   }
   ```

3. Compile TypeScript:
   ```bash
   tsc dashboard/static/js/dashboard.ts
   ```

### Testing
Run the test suite:
```bash
python manage.py test dashboard
```

### Type Checking
Check types with mypy:
```bash
pip install mypy django-stubs
mypy dashboard/
```

## Deployment

### Docker
Create `Dockerfile`:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY dashboard/requirements.txt .
RUN pip install -r requirements.txt
COPY . .
RUN python manage.py collectstatic --noinput
CMD ["gunicorn", "dashboard_project.wsgi:application", "--bind", "0.0.0.0:8000"]
```

Build and run:
```bash
docker build -t marketimmune-dashboard .
docker run -p 8000:8000 marketimmune-dashboard
```

### AWS Lambda / Serverless
Use `zappa` for AWS deployment:
```bash
pip install zappa
zappa init
zappa deploy production
```

## Performance Notes

- **Database**: SQLite suitable for < 100K records. Use PostgreSQL for production scaling.
- **Pagination**: API returns 100 items per page. Use `?page=2` for additional pages.
- **Caching**: Add Redis caching layer for frequent queries: `django-redis`
- **Static Files**: Serve with CDN (CloudFront, Cloudflare) in production

## Security

⚠️ **Production Checklist**:
- [ ] Set `DEBUG = False` in settings.py
- [ ] Use strong `SECRET_KEY` (generate with `python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'`)
- [ ] Enable HTTPS and set `SECURE_SSL_REDIRECT = True`
- [ ] Configure `ALLOWED_HOSTS` properly
- [ ] Use environment variables for sensitive config
- [ ] Enable CSRF protection
- [ ] Set secure cookie flags

## Contributing

To extend the dashboard:

1. Add new models in [dashboard/models.py](dashboard/models.py)
2. Create serializers in [dashboard/serializers.py](dashboard/serializers.py)
3. Add API endpoints in [dashboard/views.py](dashboard/views.py)
4. Update HTML templates in [dashboard/templates/dashboard/](dashboard/templates/dashboard/)
5. Extend JavaScript in [dashboard/static/js/dashboard.js](dashboard/static/js/dashboard.js)

## License

This project is part of the MarketImmune benchmark. See [LICENSE](../LICENSE) for details.

## Support

- **Documentation**: [docs/benchmark_spec.md](../docs/benchmark_spec.md)
- **Issues**: [GitHub Issues](https://github.com/Zwc-11/marketimmune-benchmark/issues)
- **Discussions**: [GitHub Discussions](https://github.com/Zwc-11/marketimmune-benchmark/discussions)

---

**MarketImmune Benchmark Dashboard** | Built with Django + Chart.js | [GitHub](https://github.com/Zwc-11/marketimmune-benchmark)
