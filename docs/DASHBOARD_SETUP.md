# MarketImmune Dashboard Setup Guide

Complete step-by-step guide for setting up, configuring, and running the MarketImmune interactive benchmark dashboard.

## Table of Contents
1. [System Requirements](#system-requirements)
2. [Installation Steps](#installation-steps)
3. [Configuration](#configuration)
4. [Running the Dashboard](#running-the-dashboard)
5. [Database Management](#database-management)
6. [API Usage](#api-usage)
7. [Troubleshooting](#troubleshooting)
8. [Advanced Configuration](#advanced-configuration)

---

## System Requirements

### Hardware
- **CPU**: 2+ cores recommended
- **RAM**: 2GB minimum for development, 4GB+ for production
- **Disk**: 500MB free space (includes database, static files, venv)

### Software
- **Python**: 3.8 or higher
- **pip**: Latest version
- **Git**: For version control
- **Node.js** (optional): For TypeScript development

### Supported Operating Systems
- ✅ Windows 10/11
- ✅ macOS 10.14+
- ✅ Linux (Ubuntu 18.04+, Debian 10+, CentOS 7+)

---

## Installation Steps

### Step 1: Environment Setup

#### Windows
```powershell
# Navigate to project directory
cd c:\Users\caesa\OneDrive\桌面\MarketImmune

# Create virtual environment
python -m venv venv

# Activate virtual environment
venv\Scripts\activate

# Verify Python path
python -c "import sys; print(sys.executable)"
```

#### macOS / Linux
```bash
cd ~/Desktop/MarketImmune  # or your project path

python3 -m venv venv

source venv/bin/activate

# Verify
python -c "import sys; print(sys.executable)"
```

### Step 2: Install Dependencies

```bash
# Upgrade pip
pip install --upgrade pip

# Install from requirements file
pip install -r dashboard/requirements.txt

# Verify installation
pip list | grep -E "Django|djangorestframework|django-cors"
```

**Expected output** (versions may vary):
```
Django                        4.2.0
djangorestframework           3.14.0
django-cors-headers          4.0.0
```

### Step 3: Database Initialization

```bash
# Apply Django migrations (creates db.sqlite3)
python manage.py migrate

# Check migration status
python manage.py showmigrations

# Create superuser (optional, for admin access)
python manage.py createsuperuser
# Follow prompts for username, email, password
```

### Step 4: Load Benchmark Data

```bash
# Load sample metrics into database
python manage.py load_metrics

# Verify data loaded
python manage.py shell
>>> from dashboard.models import ProjectStats, TaskMetric, ModelMetric
>>> print(f"Stats: {ProjectStats.objects.count()}")
>>> print(f"Tasks: {TaskMetric.objects.count()}")
>>> print(f"Models: {ModelMetric.objects.count()}")
>>> exit()
```

### Step 5: Collect Static Files

```bash
# Collect all static files for serving
python manage.py collectstatic --noinput

# Check collected files
ls -la staticfiles/js/  # or dir staticfiles\js\ on Windows
```

---

## Configuration

### Django Settings

Edit `dashboard_project/settings.py`:

```python
# 1. Debug Mode (disable in production)
DEBUG = True  # Change to False for production

# 2. Secret Key (generate new one for production)
SECRET_KEY = 'your-secret-key-here'
# Generate with:
# python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# 3. Allowed Hosts
ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'yourdomain.com']

# 4. Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
# For PostgreSQL (production):
# 'ENGINE': 'django.db.backends.postgresql',
# 'NAME': 'marketimmune_db',
# 'USER': 'postgres',
# 'PASSWORD': 'your_password',
# 'HOST': 'localhost',
# 'PORT': '5432',

# 5. CORS Configuration
CORS_ALLOWED_ORIGINS = [
    'http://localhost:3000',
    'http://localhost:8000',
    'https://yourdomain.com',
]

# 6. Static Files
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# 7. Media Files (for uploads)
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
```

### Environment Variables (Optional)

Create `.env` file in project root:

```bash
DEBUG=True
SECRET_KEY=your-generated-secret-key
ALLOWED_HOSTS=localhost,127.0.0.1,yourdomain.com
DATABASE_URL=sqlite:///db.sqlite3
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8000
LOG_LEVEL=INFO
```

Load variables in `settings.py`:

```python
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

DEBUG = os.getenv('DEBUG', 'True') == 'True'
SECRET_KEY = os.getenv('SECRET_KEY', 'default-unsafe-key')
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost').split(',')
```

---

## Running the Dashboard

### Option 1: Development Server (Recommended for Testing)

```bash
# Start development server
python manage.py runserver

# Access dashboard
# Open browser to http://localhost:8000
```

**Features**:
- Auto-reloads on code changes
- Detailed error pages
- Easy debugging
- Built-in security checks

**Console output**:
```
Starting development server at http://127.0.0.1:8000/
Quit the server with CONTROL-C.
...
[15/Jan/2026 10:30:00] "GET / HTTP/1.1" 200 5421
```

### Option 2: Production with Gunicorn

```bash
# Install Gunicorn (already in requirements.txt)
pip install gunicorn

# Run with Gunicorn
gunicorn dashboard_project.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 4 \
  --worker-class sync \
  --max-requests 1000 \
  --timeout 30

# For Windows (use quotes):
gunicorn "dashboard_project.wsgi:application" --bind 0.0.0.0:8000 --workers 4
```

**Recommended settings**:
```
Workers = CPU count * 2 (e.g., 4 cores = 8 workers)
Timeout = 30-60 seconds
Max requests = 1000-5000
Worker class = sync (default), or gevent for async
```

### Option 3: Docker Deployment

```bash
# Build Docker image
docker build -t marketimmune-dashboard .

# Run container
docker run -p 8000:8000 \
  -e DEBUG=False \
  -e SECRET_KEY=your-secret-key \
  marketimmune-dashboard

# Or with docker-compose
docker-compose up
```

### Option 4: Custom Port

```bash
# Run on different port
python manage.py runserver 0.0.0.0:8080

# Access at http://localhost:8080
```

---

## Database Management

### Backup Database

```bash
# Copy SQLite database
cp db.sqlite3 db.sqlite3.backup  # macOS/Linux
copy db.sqlite3 db.sqlite3.backup  # Windows

# For PostgreSQL
pg_dump -U postgres marketimmune_db > backup.sql
```

### Reset Database

⚠️ **Warning**: This deletes all data!

```bash
# Delete database and recreate
rm db.sqlite3  # or delete db.sqlite3 on Windows
python manage.py migrate
python manage.py load_metrics
```

### Export Data

```bash
# Export to JSON
python manage.py dumpdata dashboard > backup.json

# Export specific model
python manage.py dumpdata dashboard.TaskMetric > tasks.json
```

### Import Data

```bash
# Load from JSON
python manage.py loaddata backup.json

# Or load from fixture
python manage.py loaddata dashboard/fixtures/initial_data.json
```

### Database Shell

```bash
# Access Django shell
python manage.py shell

# Query examples
from dashboard.models import TaskMetric, ModelMetric
tasks = TaskMetric.objects.all()
for task in tasks:
    print(f"{task.task_display}: PR-AUC={task.pr_auc}")

models = ModelMetric.objects.filter(rank__lte=3).order_by('rank')
for model in models:
    print(f"{model.model_display} (Rank {model.rank}): {model.pr_auc}")

exit()
```

---

## API Usage

### Access API Endpoints

Open browser or use `curl`:

```bash
# Dashboard homepage
curl http://localhost:8000/

# API summary (all data)
curl http://localhost:8000/api/summary/

# Project statistics
curl http://localhost:8000/api/stats/

# Leaderboard
curl http://localhost:8000/api/leaderboard/

# Task metrics (paginated)
curl "http://localhost:8000/api/task-metrics/?page=1"

# Phase 7 details
curl http://localhost:8000/api/phase/7/
```

### API Response Examples

**GET /api/summary/** returns:
```json
{
  "stats": {
    "total_examples": 18000,
    "total_tasks": 6,
    "total_phases": 9,
    "total_models": 2,
    "test_coverage": 100.0,
    "type_errors": 0,
    "linting_violations": 0,
    "test_count": 123,
    "last_updated": "2026-01-15T10:30:00Z"
  },
  "task_metrics": [...],
  "model_metrics": [...]
}
```

### Filtering & Pagination

```bash
# Paginate results
curl "http://localhost:8000/api/task-metrics/?page=2&page_size=50"

# Filter by search
curl "http://localhost:8000/api/task-metrics/?search=event"

# Sort by field
curl "http://localhost:8000/api/model-metrics/?ordering=-rank"
```

---

## Troubleshooting

### Common Issues & Solutions

#### 1. "ModuleNotFoundError: No module named 'django'"

**Cause**: Virtual environment not activated

**Solution**:
```bash
# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

#### 2. "No such table: dashboard_taskmetric"

**Cause**: Migrations not applied

**Solution**:
```bash
python manage.py migrate
python manage.py load_metrics
```

#### 3. "Port 8000 already in use"

**Cause**: Another process using port 8000

**Solution**:
```bash
# Use different port
python manage.py runserver 8001

# Or kill existing process
# Windows
netstat -ano | findstr :8000
taskkill /PID <PID> /F

# macOS/Linux
lsof -i :8000
kill -9 <PID>
```

#### 4. "CORS errors" in browser console

**Cause**: Frontend on different origin than Django

**Solution**:
```python
# In settings.py, update CORS_ALLOWED_ORIGINS
CORS_ALLOWED_ORIGINS = [
    'http://localhost:3000',  # Your frontend
    'http://localhost:8000',  # Django server
]
```

#### 5. "Static files not loading" (404 errors)

**Cause**: Static files not collected

**Solution**:
```bash
python manage.py collectstatic --noinput

# In development, Django serves automatically
# In production, configure web server (Nginx, Apache)
```

#### 6. "Page loads but no data displays"

**Cause**: Database empty

**Solution**:
```bash
python manage.py load_metrics
python manage.py shell
>>> from dashboard.models import ProjectStats
>>> ProjectStats.objects.count()  # Should return > 0
```

---

## Advanced Configuration

### Enable Caching

Install Redis:
```bash
pip install django-redis
```

Update `settings.py`:
```python
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
    }
}
```

Use in views:
```python
from django.core.cache import cache

@api_view(['GET'])
def dashboard_summary(request):
    data = cache.get('dashboard_summary')
    if data is None:
        # Compute data
        data = {...}
        cache.set('dashboard_summary', data, 3600)  # Cache 1 hour
    return Response(data)
```

### Enable Logging

```python
# In settings.py
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'logs', 'django.log'),
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['file'],
        'level': 'INFO',
    },
}
```

### Setup PostgreSQL (Production)

```bash
# Install PostgreSQL adapter
pip install psycopg2-binary

# Update settings.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'marketimmune_db',
        'USER': 'postgres',
        'PASSWORD': 'your_password',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}

# Apply migrations
python manage.py migrate
```

### Deploy to AWS

1. **EC2 Instance Setup**:
   ```bash
   sudo apt-get update
   sudo apt-get install python3-venv python3-pip
   git clone https://github.com/Zwc-11/marketimmune-benchmark.git
   cd marketimmune-benchmark
   python3 -m venv venv
   source venv/bin/activate
   pip install -r dashboard/requirements.txt
   ```

2. **Gunicorn + Nginx**:
   ```bash
   # Install Nginx
   sudo apt-get install nginx
   
   # Configure Nginx to proxy to Gunicorn
   sudo nano /etc/nginx/sites-available/default
   ```

3. **Systemd Service** (auto-start):
   ```bash
   sudo nano /etc/systemd/system/marketimmune.service
   ```
   
   ```ini
   [Unit]
   Description=MarketImmune Dashboard
   After=network.target

   [Service]
   User=ubuntu
   WorkingDirectory=/home/ubuntu/marketimmune-benchmark
   ExecStart=/home/ubuntu/marketimmune-benchmark/venv/bin/gunicorn \
     dashboard_project.wsgi:application --bind 127.0.0.1:8000

   [Install]
   WantedBy=multi-user.target
   ```

4. **Enable and start**:
   ```bash
   sudo systemctl enable marketimmune
   sudo systemctl start marketimmune
   sudo systemctl status marketimmune
   ```

---

## Performance Optimization

### Caching Strategies
- Cache API responses: 1 hour
- Cache static assets: 1 month
- Cache database queries: 5 minutes

### Database Optimization
- Add indexes on frequently queried fields
- Use `select_related()` and `prefetch_related()` for joins
- Archive old data to separate tables

### Frontend Optimization
- Minify JavaScript and CSS
- Lazy-load chart data
- Implement infinite scroll for large datasets
- Use service workers for offline support

---

## Next Steps

1. ✅ Complete setup (you are here)
2. 📊 Customize dashboard styling
3. 📈 Load your benchmark data
4. 🚀 Deploy to production
5. 📱 Add mobile app integration
6. 🔐 Implement authentication

For detailed API documentation, see [API Documentation](../dashboard/README.md#api-documentation).

---

**Last Updated**: January 15, 2026  
**Version**: 1.0  
**Maintainer**: MarketImmune Team
