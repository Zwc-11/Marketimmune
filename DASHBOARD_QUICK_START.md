# MarketImmune Dashboard - Quick Reference Card

## 🚀 Start Dashboard in 3 Steps

### Windows
```bash
setup_dashboard.bat
python manage.py runserver
# Open http://localhost:8000
```

### macOS/Linux
```bash
chmod +x setup_dashboard.sh && ./setup_dashboard.sh
source venv/bin/activate
python manage.py runserver
# Open http://localhost:8000
```

### Manual Setup
```bash
python -m venv venv && source venv/bin/activate
pip install -r dashboard/requirements.txt
python manage.py migrate
python manage.py load_metrics
python manage.py runserver
```

---

## 📊 Dashboard Sections

| Section | URL | Features |
|---------|-----|----------|
| **Home** | `/` | Stats, timeline, hero |
| **Benchmarks** | `/#benchmarks` | 4 interactive charts |
| **Metrics** | `/#benchmarks` | Table with all 6 tasks |
| **Leaderboard** | `/#leaderboard` | Model rankings (🥇🥈🥉) |
| **Quality** | Page | Coverage, tests, types |
| **API** | `/api/summary/` | JSON data endpoint |

---

## 🔌 API Quick Reference

```bash
# Get all data
curl http://localhost:8000/api/summary/

# Get leaderboard
curl http://localhost:8000/api/leaderboard/

# Get phase 7
curl http://localhost:8000/api/phase/7/

# Get task metrics (paginated)
curl "http://localhost:8000/api/task-metrics/?page=1"

# Admin panel
# http://localhost:8000/admin/
```

---

## ⚙️ Common Commands

```bash
# Start server
python manage.py runserver

# Create admin user
python manage.py createsuperuser

# Load data
python manage.py load_metrics

# Reset database
python manage.py flush && python manage.py migrate && python manage.py load_metrics

# Run on different port
python manage.py runserver 8080

# Collect static files (production)
python manage.py collectstatic --noinput

# Gunicorn production server
gunicorn dashboard_project.wsgi:application --bind 0.0.0.0:8000
```

---

## 📁 Key Files

| File | Purpose |
|------|---------|
| `settings.py` | Django configuration |
| `models.py` | Database models (4 total) |
| `views.py` | API endpoints (7 total) |
| `index.html` | Dashboard UI (Tailwind CSS) |
| `dashboard.js` | Frontend logic & charts |
| `requirements.txt` | Python dependencies |

---

## 🎯 Database Models

1. **BenchmarkMetrics** - Phase info (9 records)
2. **TaskMetric** - Task performance (6+ per phase)
3. **ModelMetric** - Model rankings
4. **ProjectStats** - Overall statistics (1 record)

---

## 🐳 Docker

```bash
# Build
docker build -t marketimmune-dashboard .

# Run
docker run -p 8000:8000 marketimmune-dashboard

# With docker-compose
docker-compose up
```

---

## 🆘 Troubleshooting

| Problem | Fix |
|---------|-----|
| Module not found | Activate venv: `source venv/bin/activate` |
| Port 8000 in use | Use different port: `runserver 8080` |
| No data visible | Load data: `python manage.py load_metrics` |
| 404 on static files | Collect: `python manage.py collectstatic` |
| Database error | Reset: `python manage.py migrate --fake-initial` |

---

## 📚 Documentation

- **Complete Setup**: `docs/DASHBOARD_SETUP.md` (50+ pages)
- **Implementation**: `docs/DASHBOARD.md` (features & architecture)
- **Dashboard Info**: `dashboard/README.md` (overview & API)

---

## ✨ Features Included

✅ 7 REST API endpoints  
✅ 4 interactive charts  
✅ Responsive design (mobile-friendly)  
✅ Django admin interface  
✅ Setup automation scripts  
✅ Docker support  
✅ TypeScript configuration  
✅ Comprehensive documentation  

---

## 🎨 Tech Stack

- **Backend**: Django 4.2 + REST Framework 3.14
- **Database**: SQLite (upgradeable to PostgreSQL)
- **Frontend**: HTML + JavaScript + Tailwind CSS
- **Charts**: Chart.js 4.4
- **Server**: Gunicorn 20.1

---

## 🌐 URLs Cheat Sheet

```
http://localhost:8000/              # Dashboard
http://localhost:8000/admin/        # Admin panel
http://localhost:8000/api/summary/  # API data
http://localhost:8000/api/leaderboard/  # Model rankings
http://localhost:8000/api/phase/7/  # Phase 7 metrics
```

---

## 📈 Performance

- ⚡ Development: 100+ concurrent users (SQLite)
- 🚀 Production: 1000+ concurrent users (PostgreSQL + Gunicorn)
- 📊 Scaling: Load-balanced with reverse proxy

---

## 🔐 Security

- ✅ CSRF protection enabled
- ✅ CORS configured
- ✅ Debug mode disableable
- ✅ Session security
- ✅ SQL injection prevention (via ORM)

---

**Last Updated**: January 15, 2026  
**Version**: 1.0  
**Status**: ✅ Ready to Use
