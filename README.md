# Laguna-AI Backend
AI line-balancing backend application.

## Project Structure (Optimized)

```
Backend/                             # Project root
├── apps/                            # All Django applications
│   ├── absenteeism/                # Absenteeism prediction engine
│   │   ├── migrations/
│   │   ├── management/commands/
│   │   ├── templates/
│   │   ├── views.py
│   │   ├── models.py
│   │   ├── urls.py
│   │   ├── utils.py
│   │   └── ...
│   ├── accounts/                   # User authentication & management
│   │   ├── api/                    # API boundary (views/serializers)
│   │   ├── services/               # Domain/service layer (incremental)
│   │   ├── migrations/
│   │   ├── templates/
│   │   ├── utils/
│   │   ├── views.py                # Backward-compatible re-export
│   │   ├── serializers.py          # Backward-compatible re-export
│   │   ├── models.py
│   │   └── ...
│   ├── dataEngine/                 # Data processing & employee management
│   │   ├── migrations/
│   │   ├── management/commands/
│   │   ├── views.py
│   │   ├── models.py
│   │   └── ...
│   ├── manning_sheet/              # Manning sheet & resource planning
│   │   ├── migrations/
│   │   ├── management/commands/
│   │   ├── views.py
│   │   ├── models.py
│   │   └── ...
│   └── __init__.py
│
├── backend_laguna/                 # Django project configuration
│   ├── settings/                   # Environment-specific settings
│   │   ├── __init__.py
│   │   ├── base.py                # Shared settings
│   │   ├── dev.py                 # Development settings
│   │   └── prod.py                # Production settings
│   ├── settings.py                # Settings router
│   ├── urls.py                    # Main URL configuration
│   ├── wsgi.py                    # WSGI application
│   ├── asgi.py                    # ASGI application
│   ├── custom_middleware.py       # Custom middleware
│   └── utils.py                   # Utility functions
│
├── core/                           # Shared utilities & configurations
│   ├── app_scheduler.py           # APScheduler configuration
│   └── __init__.py
│
├── static/                         # Static files (CSS, JS, images)
├── media/                          # User-uploaded media
├── data/                           # Data files (CSV, fixtures)
├── logs/                           # Application logs (auto-created)
├── tests/                          # Integration tests
│
├── manage.py                       # Django management script
├── run.py                          # Setup & migration runner
├── requirements.txt                # Python dependencies
├── .env                            # Environment variables (create from .env.example)
├── .env.example                    # Environment variables template
├── .gitignore                      # Git ignore rules
├── sonar-project.properties        # SonarQube configuration
└── README.md                       # This file

```

## Environment Setup

### Development Environment
1. Copy `.env.example` to `.env`
2. Update `.env` with your development settings
3. Set `ENVIRONMENT=development` in `.env`
4. The app will automatically use `backend_laguna/settings/dev.py`

### Production Environment
1. Set `ENVIRONMENT=production` in `.env`
2. Configure all required environment variables
3. The app will automatically use `backend_laguna/settings/prod.py`

## Running the Application

### Setup & Migrations
```bash
python run.py
```

### Docker (single file setup)
```bash
# Development stack
docker compose --profile dev up --build -d

# Optional scheduler in development
docker compose --profile dev --profile scheduler up -d

# Production-mode services (gunicorn + celery + nginx)
docker compose --profile prod up --build -d
```

### App Health Check
- Root endpoint: `GET /`
- Success response:
```json
{"message":"app is running successfully"}
```

- Unknown path response:
```json
{"error": "Unknown request path"}
```

### pgAdmin (with Docker)
```bash
# Start pgAdmin in dev profile
docker compose --profile dev up -d pgadmin
```

- URL: `http://localhost:5050`
- Default login email: `admin@laguna.com`
- Default password: `admin123`
- To override, set in `.env`:
  - `PGADMIN_DEFAULT_EMAIL`
  - `PGADMIN_DEFAULT_PASSWORD`
  - `PGADMIN_PORT`

### Local Python (without Docker)
```bash
# 1) Create virtual environment
python -m venv .venv

# 2) Activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# Windows (cmd)
.venv\Scripts\activate.bat

# 3) Install dependencies
pip install -r requirements.txt

# 4) Configure environment
# copy .env.example to .env and update values

# 5) Run migrations
python run.py

# 6) Start development server
python manage.py runserver
```

### Direct Production Run (non-Docker)
```bash
ENVIRONMENT=production gunicorn backend_laguna.wsgi
```

### Background Schedulers
```bash
python manage.py absenteeism_scheduler
python manage.py dataEngine_scheduler
python manage.py manning_sheet_scheduler
```

## Quick Start

```bash
# 1) Start app in Docker (recommended)
docker compose --profile dev up --build -d

# 2) Open API
# http://localhost:8001

# 3) Check health endpoint
curl http://localhost:8001/
```

## Key Features

- **Modular Apps**: Each feature isolated in `apps/` folder
- **Environment-Aware Config**: Separate settings for dev/prod
- **Shared Utilities**: Reusable code in `core/` folder
- **Background Jobs**: APScheduler for automated tasks
- **Production-Ready**: Proper static/media/logs separation

## Important Notes

- Django recognizes app labels (accounts, absenteeism, etc.) from INSTALLED_APPS
- Database migrations are preserved and functional
- All environment variables should be in `.env` (never commit this file)
- Use `.env.example` as template for new environments
- Docker profiles used in this project:
  - `dev`: backend + db + redis + pgadmin
  - `scheduler`: optional scheduler service
  - `prod`: backend_prod + celery + nginx + db + redis
