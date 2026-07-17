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

---

## 🧠 Architecture Deep Dive

This section explains the internal mechanics of the `Dockerfile` build process and the `docker-compose.yml` services.

### 1. Multi-Stage Dockerfile (`backend/Dockerfile`)

The backend uses a **multi-stage build** approach to keep the final image size small and secure. It splits the build process into distinct stages:

#### The `builder` Stage
- **Purpose:** Entirely dedicated to downloading and compiling Python dependencies.
- **How it works:** Installs heavy system tools (like `gcc`) required to build certain Python packages (like database drivers). It then installs packages from `requirements.txt`.
- **Why:** We exclude the `gcc` compiler from the final production image to save space and reduce security vulnerabilities.

#### The `base` Stage
- **Purpose:** The core runtime image. Starts completely fresh from a slim Python image.
- **How it works:** 
  - Installs lightweight database clients (MySQL/Postgres) needed to *connect* to the database.
  - Reaches back into the `builder` stage and copies **only** the finished, compiled Python packages (`/root/.local`).
  - Sets optimizations like `PYTHONUNBUFFERED=1` (for instant logs) and `PYTHONDONTWRITEBYTECODE=1` (prevents `.pyc` files).
  - Copies the application code and sets up a `HEALTHCHECK` to ensure the server hasn't crashed.

#### The `dev` & `prod` Targets
- **`dev`**: Uses the `base` stage and runs the standard Django development server (`manage.py runserver`). Used for local development with hot-reloading.
- **`prod`**: Uses the `base` stage but runs using **Gunicorn**, a robust, production-grade web server capable of handling multiple requests at once via worker processes.

### 2. Microservices Architecture (`docker-compose.yml`)

The `docker-compose.yml` file defines 11 different isolated services that communicate seamlessly to form a complete, production-ready environment.

#### The Data Layer (Storage & Caching)
- **`db`**: A PostgreSQL 15 database storing permanent application data.
- **`redis`**: An in-memory data store used for caching and acting as a message broker for Celery background tasks.

#### The Management UIs (Developer Tools)
- **`pgadmin`**: A graphical web interface (port 5050) to manage the PostgreSQL database.
- **`redis-commander`**: A graphical web interface (port 8082) to view and manage the Redis cache.

#### The Core Application Layer
- **`backend`**: The main Django application (built from the `dev` target). It automatically runs database migrations (`migrate`) before starting.
- **`celery`**: A Celery background worker handling long-running asynchronous tasks (like sending emails) so the main server remains responsive.
- **`scheduler`**: Runs a custom script that launches the three individual app schedulers (`absenteeism_scheduler`, `dataEngine_scheduler`, `manning_sheet_scheduler`) simultaneously in the background.
- **`app`**: The Frontend web application (React/Vue) running on port 5173.

#### The Gateway
- **`nginx`**: A high-performance reverse proxy. It listens on standard web ports (80/443), serves static files extremely fast, and routes complex dynamic requests to the Django backend.

#### The Observability Layer (Monitoring & Logs)
- **`loki`**: A log aggregation system (built by Grafana) acting as a database for container logs.
- **`promtail`**: The scraper that watches the Docker engine, grabs console logs from *all* containers, and ships them to `loki`.
- **`grafana`**: A visualization dashboard (port 4000) used to view charts, metrics, and search through all logs collected by Loki.

#### Persistent Volumes
At the bottom of the compose file, named volumes (like `postgres_data` and `media_volume`) are defined. These act as permanent virtual hard drives ensuring that the database, uploaded files, and logs survive container restarts.
