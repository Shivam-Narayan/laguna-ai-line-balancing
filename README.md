# Laguna-AI Backend
AI line-balancing backend application.

## Project Structure (Restructured)

```text
laguna-ai-line-balancing/             # Repository root
├── backend/                          # Lowercase backend code directory
│   ├── apps/                         # All Django applications
│   │   ├── absenteeism/             # Absenteeism prediction engine
│   │   ├── accounts/                # User authentication & management
│   │   ├── dataEngine/              # Data processing & employee management
│   │   └── manning_sheet/           # Manning sheet & resource planning
│   ├── backend_laguna/               # Django project configuration
│   │   └── settings/                 # Environment settings (dev, prod)
│   ├── core/                         # Shared utilities & configurations
│   ├── data/                         # Data files (CSV, fixtures)
│   ├── Dockerfile                    # Dockerfile for building backend images
│   ├── .dockerignore                 # Docker ignore file
│   ├── manage.py                     # Django management script
│   ├── run.py                        # Setup & migration runner
│   ├── requirements.txt              # Python dependencies
│   └── sonar-project.properties      # SonarQube configuration
├── docs/                             # Documentation (e.g. Docker configuration guides)
├── scripts/                          # Script files (e.g. docker-helper utilities)
├── tests/                            # Directory for tests
├── .env.example                      # Environment variables template
├── .gitattributes                    # Git attributes configuration
├── .gitignore                        # Git ignore rules
├── README-DEV.md                     # Developer guide
├── README.md                         # This file
├── docker-compose.yml                # Docker Compose multi-profile services
└── docker-config.yml                 # Docker Compose overrides
```

---

## Environment Setup

1. Copy `.env.example` to `.env` in the repository root:
   ```bash
   cp .env.example .env
   ```
2. Update `.env` with your settings (database credentials, SendGrid keys, etc.).
3. Set the environment type:
   - For development: `ENVIRONMENT=development`
   - For production: `ENVIRONMENT=production`

---

## Running the Application

### 1. Docker (Recommended, run from root)
The application services are managed via Docker Compose profiles:

```bash
# Start development stack (db, redis, pgadmin, backend in dev mode)
docker compose --profile dev up --build -d

# Start development stack + background task scheduler
docker compose --profile dev --profile scheduler up -d

# Start production stack (db, redis, backend_prod, celery, nginx proxy)
docker compose --profile prod up --build -d
```

#### Health Checks
- Health endpoint: `GET http://localhost:8001/`
- Success response: `{"message":"app is running successfully"}`

#### Database UI (pgAdmin)
- Access URL: `http://localhost:5050`
- Default Credentials: `admin@laguna.com` / `admin123` (override using `PGADMIN_DEFAULT_EMAIL` and `PGADMIN_DEFAULT_PASSWORD` in `.env`).

---

### 2. Local Python (Without Docker)
To run the server natively on your host machine:

```bash
# 1) Navigate to the backend directory
cd backend

# 2) Create a virtual environment
python -m venv .venv

# 3) Activate virtual environment
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# Windows (cmd)
.venv\Scripts\activate.bat
# Linux/macOS
source .venv/bin/activate

# 4) Install python dependencies
pip install -r requirements.txt

# 5) Run setup and database migrations
python run.py

# 6) Start the local development server
python manage.py runserver
```

#### Running Schedulers Natively
From the `backend/` directory:
```bash
python manage.py absenteeism_scheduler
python manage.py dataEngine_scheduler
python manage.py manning_sheet_scheduler
```

---

## Key Features
- **Modular Django Architecture**: All features are organized under separate apps in the `backend/apps/` directory.
- **Environment-Aware Settings**: Settings are split dynamically into `base.py`, `dev.py`, and `prod.py` configs under `backend/backend_laguna/settings/`.
- **Dockerized Deployments**: Clean configurations separating development tools from production servers (Gunicorn + Celery + Nginx).
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
