# ✅ Docker Setup Complete

## 📦 What Was Created

Your Laguna AI Line Balancing application uses a **Unified Docker Setup**, meaning a single `docker-compose.yml` file handles both development and production deployments based on your `.env` configuration.

### 📂 Docker Files & Scripts

#### Core Docker Files
```text
laguna-ai-line-balancing/
├── docker-compose.yml           # Base orchestration (db, redis, frontend, logging)
├── docker-compose.override.yml  # Dev overrides (local volume mounts, pgadmin)
├── docker-compose.prod.yml      # Prod overrides (celery, scheduler, nginx, gunicorn)
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

The architecture is split into three layered files: `docker-compose.yml` (Base), `docker-compose.override.yml` (Dev), and `docker-compose.prod.yml` (Prod).

### Base Services (`docker-compose.yml`)
- **db**: PostgreSQL database (port 5432)
- **redis**: Cache and message broker (port 6379)
- **app**: Frontend React Application (port 5173)
- **loki**, **promtail**, **grafana**: Centralized logging and monitoring

### Development Overrides (`docker-compose.override.yml`)
- **backend**: Django API server (runs development server with local volume mounts)
- **pgadmin**: Web UI for PostgreSQL (port 5050)
- **redis-commander**: Web UI for Redis (port 8082)

### Production Overrides (`docker-compose.prod.yml`)
- **backend**: Django API server (runs production Gunicorn server)
- **celery**: Production background task worker
- **scheduler**: Background scheduler for absenteeism and manning sheet generation
- **nginx**: Reverse proxy serving static files and routing traffic

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

This `Dockerfile` is written using a **multi-stage build** approach. This is considered a best practice in Docker because it keeps your final image size very small and secure. 

It works by splitting the build process into different "stages." Here is the step-by-step breakdown of how it works:

#### The `builder` Stage (Lines 2-17)
```dockerfile
FROM python:3.11-slim AS builder
```
- **Purpose:** This stage is entirely dedicated to downloading and compiling your Python dependencies.
- **What it does:** It installs heavy system tools (like `gcc`, a C-compiler) that are required to build certain Python packages (like database drivers for MySQL/Postgres). It then installs your `requirements.txt`.
- **Why:** We don't want to include the `gcc` compiler in the final production image because it makes the image huge and creates a security risk.

#### The `base` Stage (Lines 19-52)
```dockerfile
FROM python:3.11-slim AS base
```
- **Purpose:** This is the core image that will actually run your application. It starts completely fresh.
- **Dependencies:** It installs only the lightweight database clients (MySQL/Postgres) needed to *connect* to the database, skipping the heavy compilers.
- **Copying Packages:** (`COPY --from=builder...`) It reaches back into the `builder` stage and copies **only** the finished, compiled Python packages (`/root/.local`). 
- **Environment Variables (`ENV`):**
  - `PYTHONUNBUFFERED=1`: Ensures Python outputs logs directly to the terminal without buffering (great for seeing logs immediately in Docker).
  - `PYTHONDONTWRITEBYTECODE=1`: Stops Python from creating `.pyc` files, saving disk space.
  - `PYTHONPATH=/app/apps:/app`: Tells Python exactly where to look when you write `import ...` in your code.
- **Setup:** It copies your actual code (`COPY . .`), creates necessary folders for logs and media, and sets up a `HEALTHCHECK`. The health check tells Docker to ping `http://localhost:8000/admin/` every 30 seconds to ensure the server hasn't crashed.

#### The `dev` Target (Lines 54-56)
```dockerfile
FROM base AS dev
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
```
- **Purpose:** Used for local development.
- **What it does:** It takes the `base` stage and runs the standard Django development server. When you build this image (e.g., via docker-compose targeting `dev`), it gives you hot-reloading.

#### The `prod` Target (Lines 58-60)
```dockerfile
FROM base AS prod
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4"]
```
- **Purpose:** Used for your live production servers.
- **What it does:** It takes the exact same `base` stage but runs it using **Gunicorn**, a robust, production-grade web server capable of handling multiple requests at once using 4 worker processes.

**Summary:** This Dockerfile allows you to run `docker build --target dev` for local testing, or `docker build --target prod` for a highly optimized, compiler-free, production-ready image!

### 2. Microservices Architecture (Layered Docker Compose)

This setup is incredibly well-structured. It defines a complete, production-ready **microservices architecture** using a **layered compose approach**.

Instead of a monolithic file, the setup is split into `docker-compose.yml` (Base), `docker-compose.override.yml` (Dev environment UI tools and live-reloading), and `docker-compose.prod.yml` (Production workers, Nginx, and Gunicorn).

Here is a breakdown of the entire architecture:

#### The Data Layer (Storage & Caching) - Base
- **`db`**: A PostgreSQL 15 database. It stores all your application's permanent data. It uses a `healthcheck` to ensure the database is fully booted before letting other services connect to it.
- **`redis`**: An in-memory data store. This is typically used for caching data to make the app faster, and it also acts as the "message broker" for Celery background tasks.

#### The Management UIs (Tools for Developers) - Dev Override
- **`pgadmin`**: A graphical web interface (running on port 5050) that lets you easily view and manage your PostgreSQL database without writing SQL in the terminal.
- **`redis-commander`**: A graphical web interface (port 8082) for looking inside your Redis cache.

#### The Core Application Layer
- **`backend`**: Your main Django application. In dev, it mounts your local files for live-reloading. In prod, it uses a baked Docker image running Gunicorn. Both automatically run database migrations (`migrate`) on boot.
- **`celery`** (Prod): A Celery background worker for long-running background tasks.
- **`scheduler`** (Prod): This container runs a custom script that launches your three individual app schedulers simultaneously in the background. 
- **`app`** (Base): Your Frontend web application (running on port 5173 for dev).

#### The Gateway - Prod Override
- **`nginx`**: A high-performance web server acting as a "Reverse Proxy". It sits in front of your backend, listens on standard web ports (80 and 443 for HTTPS), and serves your static files (like CSS/images) extremely fast.

#### The Observability Layer (Monitoring & Logs)
- **`loki`**: A log aggregation system built by Grafana. It acts like a giant database specifically for storing logs from all your different containers.
- **`promtail`**: This is the "scraper". Notice it mounts the `/var/run/docker.sock`. It constantly watches the Docker engine, grabs the console logs from *all* your containers, and ships them to `loki`.
- **`grafana`**: A beautiful visualization dashboard (port 4000). You log into this to view charts, graphs, and search through all the logs collected by Loki.

#### Volumes
At the very bottom, you see a `volumes:` block. Docker containers are temporary; if they crash, all data inside is lost. These named volumes (like `postgres_data` and `media_volume`) act like permanent virtual hard drives plugged into the containers, ensuring your database, uploaded files, and logs survive restarts!
