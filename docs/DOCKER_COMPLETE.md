# ✅ Docker Setup Complete

## 📦 What Was Created

Your Laguna AI Line Balancing application uses a **Unified Docker Setup**, meaning a single `docker-compose.yml` file handles both development and production deployments based on your `.env` configuration.

### 📂 Docker Files & Scripts

#### Core Docker Files
```text
laguna-ai-line-balancing/
├── docker-compose.yml           # Unified orchestration for all services
├── backend/
│   └── Dockerfile               # Multi-stage Dockerfile for the backend
├── nginx.conf                   # Nginx reverse proxy configuration
├── promtail-config.yml          # Configuration for Promtail log scraper
└── .dockerignore                # Files to exclude from Docker build
```

#### Helper Scripts
Located in the `scripts/` directory:
```text
├── start.bat                    # Windows Command Prompt helper
├── start.ps1                    # Windows PowerShell helper
└── start.sh                     # Linux/Mac helper
```

## 🎯 Services Included

The `docker-compose.yml` orchestrates the following services:

### Application Services
- **backend**: Django API server (runs development server or Gunicorn based on `.env`)
- **app**: Frontend React Application (port 5173)
- **scheduler**: Background scheduler for absenteeism and manning sheet generation
- **celery**: Production task queue worker

### Data & Caching
- **db**: PostgreSQL database (port 5432)
- **redis**: Cache and message broker (port 6379)

### Monitoring & UI Tools
- **pgadmin**: Web UI for PostgreSQL (port 5050)
- **redis-commander**: Web UI for Redis (port 8082)
- **grafana**: Log visualization and monitoring dashboards (port 4000)
- **loki**: Log aggregation backend
- **promtail**: Scrapes Docker logs and pushes to Loki

## 🚀 Quick Start

### Using the Helper Scripts (Recommended)

**Windows (Command Prompt):**
```cmd
scripts\start.bat --dev
```

**Windows (PowerShell):**
```powershell
.\scripts\start.ps1 -Dev
```

**Linux / macOS:**
```bash
chmod +x scripts/start.sh
./scripts/start.sh
```

### Accessing the Application

Once started, your services are available at:
- **Frontend App**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **Swagger Docs**: http://localhost:8000/swagger/
- **Grafana Logs**: http://localhost:4000 (admin / admin)
- **pgAdmin**: http://localhost:5050
- **Redis UI**: http://localhost:8082

## 🛠️ Helper Script Commands

The helper scripts (`start.bat`, `start.ps1`, `start.sh`) provide the following flags:

| Command | Description |
|---|---|
| `--dev` | Start development services |
| `--prod` | Start production services (adds celery & nginx) |
| `--build` | Rebuild all Docker images |
| `--down` | Stop and remove all containers |
| `--clean` | Stop containers and remove volumes (**DATA LOSS!**) |
| `--logs` | Tail logs for all running containers |
| `--status` | Show status of all containers |
| `--migrate` | Run database migrations |
| `--shell` | Open Django interactive shell |
| `--superuser`| Create a Django superuser (uses `.env` credentials) |

## 🔧 Configuration Management

The behavior of your Docker containers is controlled entirely by your `.env` file at the root of the project.

```env
# Controls whether Django uses debug mode and Gunicorn vs runserver
ENVIRONMENT=development  # or 'production'

# Database Settings
DB_ENGINE=django.db.backends.postgresql
DB_NAME=Laguna
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=db  # Resolves automatically in Docker
DB_PORT=5432

# CORS & CSRF Security (Required for Docker/Nginx Proxy)
CORS_ALLOWED_ORIGINS=http://localhost:5173,http://localhost:8000

# Superuser Auto-Provisioning
DJANGO_SUPERUSER_EMAIL=admin@example.com
DJANGO_SUPERUSER_PASSWORD=Laguna@Admin
```

## 🔒 Security Built-in

✅ **Environment-based secrets** (no hardcoded passwords).
✅ **CSRF & CORS Protected** out of the box for Nginx/Docker proxy environments.
✅ **Multi-stage Dockerfile** for smaller, secure production images.
✅ **Health checks** for database and redis.
✅ **Automatic service restart** on failure.

## ✅ Verification Checklist

After running `scripts\start.bat --dev`:

- [ ] `docker compose ps` shows containers are running and "healthy"
- [ ] You can access the Frontend at http://localhost:5173
- [ ] You can access the Backend API at http://localhost:8000
- [ ] You can log into the Django Admin at http://localhost:8000/admin/ with your `.env` credentials
- [ ] You can access Grafana logs at http://localhost:4000
