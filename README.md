# Laguna-AI Backend
AI line-balancing backend application.

## Project Structure

```text
laguna-ai-line-balancing/             # Repository root
├── backend/                          # Backend code directory
│   ├── apps/                         # All Django applications
│   │   ├── absenteeism/              # Absenteeism prediction engine
│   │   ├── accounts/                 # User authentication & management
│   │   ├── core/                     # Shared base models & utilities
│   │   ├── data_engine/              # Data processing & employee management
│   │   └── manning_sheet/            # Manning sheet & resource planning
│   ├── config/                       # Django project configuration
│   │   └── settings.py               # Environment-aware settings
│   ├── csv_files/                    # Auto-generated CSV exports
│   ├── data/                         # Data files (CSV, fixtures)
│   ├── Dockerfile                    # Dockerfile for building backend images
│   ├── .dockerignore                 # Docker ignore file
│   ├── manage.py                     # Django management script
│   ├── run.py                        # Setup & migration runner
│   ├── requirements.txt              # Python dependencies
│   └── sonar-project.properties      # SonarQube configuration
├── docs/                             # Documentation
├── scripts/                          # Startup scripts (start.bat, start.ps1, start.sh)
├── tests/                            # Directory for tests
├── .env.example                      # Environment variables template
├── .gitattributes                    # Git attributes configuration
├── .gitignore                        # Git ignore rules
├── docker-compose.yml                # Unified Docker Compose (all environments)
├── nginx.conf                        # Nginx reverse proxy configuration
├── promtail-config.yml               # Promtail log scraper configuration
├── README-DEV.md                     # Developer guide
└── README.md                         # This file
```

---

## 📚 Documentation Hub

| Document | Purpose |
| :--- | :--- |
| 🏗️ [System Architecture](docs/system_architecture.md) | High-level system design, DDD structure, and Data Pipeline diagrams |
| 📖 [API Endpoints Guide](docs/api_endpoints_guide.md) | Frontend integration guide (or visit `/swagger/` when running) |
| 🐳 [Docker Complete](docs/DOCKER_COMPLETE.md) | Setup, configuration, and environment variable references |
| 🚀 [Kubernetes & Deployment](docs/kubernetes_guide.md) | Production deployment architecture, K8s vs Docker Compose, and cloud testing |
| 🚑 [Operations Runbook](docs/runbook.md) | Troubleshooting, log extraction, and database backup procedures |
| 🤖 [CI/CD Pipeline](docs/ci_cd_pipeline.md) | GitHub Actions automation and deployment protections |

---

## Prerequisites

Before starting, clone **both** repositories side-by-side in the same parent directory:

```bash
# Clone both repos into the same parent folder
git clone https://github.com/Shivam-Narayan/laguna-ai-line-balancing.git
git clone https://github.com/Shivam-Narayan/laguna-ai-line-balancing-app.git
```

Your folder structure should look like:
```text
parent-folder/
├── laguna-ai-line-balancing/       # Backend (this repo)
└── laguna-ai-line-balancing-app/    # Frontend (React app)
```

> [!IMPORTANT]
> The `docker-compose.yml` references the frontend app at `../laguna-ai-line-balancing-app`. Both repos **must** be cloned as siblings, otherwise the frontend container will fail to build.

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

> [!NOTE]
> When running with Docker, the `DB_HOST` is automatically overridden to `db` (the Docker service name) by `docker-compose.yml`. You do **not** need to change `DB_HOST` in your `.env` file for Docker usage.

> [!IMPORTANT]
> The same `docker-compose.yml` is used for both development and production. The `ENVIRONMENT` variable in your `.env` file controls which mode Django runs in.

---

## Running the Application

### 1. Docker (Recommended)
You can manage and run the application services using the provided startup scripts (recommended) or manual Docker Compose commands.

#### A. Using Startup Scripts
* **Windows (Command Prompt):**
  ```cmd
  scripts\start.bat --dev
  ```
* **Windows (PowerShell):**
  ```powershell
  .\scripts\start.ps1 -Dev
  ```
* **Linux / macOS:**
  ```bash
  chmod +x scripts/start.sh
  ./scripts/start.sh
  ```

##### Script Commands

| Command | Description |
|---|---|
| `--dev` / `-Dev` | Start dev services (db + redis + backend + nginx + pgadmin) |
| `--prod` / `-Prod` | Start production services (db + redis + backend + celery + nginx) |
| `--build` / `-Build` | Rebuild Docker images and start services |
| `--down` / `-Down` | Stop and remove all containers |
| `--clean` / `-Clean` | Stop containers and remove volumes (**DATA LOSS!**) |
| `--logs` / `-Logs` | Tail logs for all running containers |
| `--status` / `-Status` | Show status of all containers |
| `--local` / `-Local` | Start Django dev server locally (no Docker) |
| `--migrate` / `-Migrate` | Run database migrations |
| `--makemigrations` / `-MakeMigrations` | Create new migration files |
| `--shell` / `-Shell` | Open Django interactive shell |
| `--superuser` / `-Superuser` | Create a Django superuser |
| `--test` / `-Test` | Run the test suite |
| `--backup` / `-Backup` | Backup PostgreSQL database |
| `--restore FILE` / `-Restore FILE` | Restore database from backup |
| `-h` / `-Help` | Show help |

#### B. Using Manual Docker Compose Commands
```bash
# Start all application services
docker compose up -d

# Force rebuild if you changed Python packages or Dockerfiles
docker compose up --build -d
```

#### Access Points (After Starting)

| Service | URL |
|---|---|
| Backend API | http://localhost:8000 |
| Frontend App | http://localhost:5173 |
| Swagger UI | http://localhost:8000/swagger/ |
| Redoc | http://localhost:8000/api/schema/redoc/ |
| Raw OpenAPI Schema | http://localhost:8000/api/schema/ |
| pgAdmin (Database UI) | http://localhost:5050 |
| Redis Commander | http://localhost:8082 |
| Grafana (Monitoring) | http://localhost:4000 |

#### API Documentation
The backend follows strict **RESTful conventions** (plural nouns, kebab-case) and uses a custom `RequestFilterMiddleware` to enforce an endpoint allowlist. If you add a new endpoint, you MUST add it to the allowlist in `custom_middleware.py`.

Because the API structure is dynamic, we do not hardcode the endpoint list in this README. Instead, you can view the live, interactive API documentation by visiting the **Swagger UI** (`http://localhost:8000/swagger/`). From there, you can explore all endpoints, view required payload structures, and even export the OpenAPI Schema directly into Postman.

**Postman Import Tip:** If you export the YAML schema to import into Postman, Postman will auto-generate responses by default which can clutter the collection. To avoid this, open the `Laguna-AI Line Balancing API.yaml` file in a text editor and perform a Find/Replace to change `description: No response body` to `description: ""` before importing. When importing into Postman, select "Tags" under Folder Organization.

#### Health Check
- Endpoint: `GET http://localhost:8000/`
- Success response: `{"message":"app is running successfully"}`

#### pgAdmin Credentials
- **Email:** `admin@laguna.com` / **Password:** `admin123`
- Override using `PGADMIN_DEFAULT_EMAIL` and `PGADMIN_DEFAULT_PASSWORD` in `.env`.

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

# 4) Install dependencies, generate and run database migrations
python run.py

# 5) Start the local development server
python manage.py runserver
```

#### Running Schedulers Natively
From the `backend/` directory:
```bash
python manage.py absenteeism_scheduler
python manage.py data_engine_scheduler
python manage.py manning_sheet_scheduler
```

---

## Initial Data Population (First-Time Setup)

After starting the application for the first time, the database will be empty. The Manning Sheet and Absenteeism Prediction features require data to function. Follow these steps to populate the database:

> [!IMPORTANT]
> All POST endpoints below require authentication. Log in through the frontend UI first, or use an API client (Postman) with valid JWT credentials.

### Step 1: Populate Active Employees
Fetch the real employee roster from the HR system:
```bash
# Via curl (or use Postman)
curl -X POST http://localhost:8000/manning-sheet/employees/rockhr/
```
Alternatively, upload a CSV file:
```bash
curl -X POST http://localhost:8000/manning-sheet/employees/upload/ \
  -F "file=@active_employees.csv"
```

### Step 2: Generate Employee Facts (EMP Facts)
This fetches Skill Matrix and Operations data from the Optafloor API and cross-references it with Active Employees:
```bash
curl -X POST http://localhost:8000/manning-sheet/emp-facts/generate/
```

### Step 3: Fetch Attendance Data
Pull today's attendance from the RockHR system:
```bash
curl -X POST http://localhost:8000/manning-sheet/attendance/rockhr/
```

### Step 4: Generate Absenteeism Predictions
Train the ML model and generate predictions:
```bash
curl -X POST http://localhost:8000/absenteeism/predictions/generate/
```

### Step 5: Generate Manning Sheet
Once Steps 1-3 are complete, generate the D-Day Manning Sheet:
```bash
curl -X POST http://localhost:8000/manning-sheet/manning-sheets/d-day/generate/
```

> [!NOTE]
> After the initial setup, the **scheduler service** (`docker-compose.yml` → `scheduler`) automatically runs these data fetches and predictions on a recurring schedule. You only need to do this manually for the very first run.

---

## Key Features & Architectural Standards
- **Strict Service Layer Architecture**: All features are organized under separate apps in the `backend/apps/` directory, adhering strictly to Domain-Driven Design. Heavy business logic (Pandas/ETL/ML/Database transactions) is isolated in `services/`, keeping `views.py` incredibly thin and focused only on HTTP routing.
- **Environment-Aware Settings**: A single `settings.py` dynamically adjusts behavior based on the `ENVIRONMENT` variable (development vs production).
- **Production-Grade Security**: 
  - Django 4.0+ strict `CSRF_TRUSTED_ORIGINS` validation is automatically mapped to `ALLOWED_HOSTS` to prevent Cross-Site Request Forgery while supporting Nginx/Docker proxies.
  - User deletions are protected by Django `pre_delete` signals to cleanly wipe SimpleJWT tokens (`OutstandingToken`, `BlacklistedToken`), guaranteeing database integrity and preventing foreign key crashes.
- **Centralized Templates**: Email HTML templates (e.g., CSV exports, Password Resets) are maintained in a global, centralized `backend/templates/` directory to prevent app-level name collisions and simplify rebranding.
- **Unified Docker Compose**: One `docker-compose.yml` for all environments. The `.env` file controls the behavior — no need for separate dev/prod compose files.
- **Production-Ready**: Gunicorn + Celery + Nginx with proper static/media/logs separation.

## Important Notes

- Django recognizes app labels (accounts, absenteeism, etc.) from `INSTALLED_APPS`.
- Database migrations are preserved and functional. If you add model fields (like `is_staff`), always run `python manage.py makemigrations` and `python manage.py migrate`.
- To delete users safely (with automatic token cleanup), use the **Django Admin Panel** (`http://localhost:8000/admin/`) or the authenticated **Swagger API**, rather than raw SQL in pgAdmin.
- All environment variables should be in `.env` (never commit this file).
- Use `.env.example` as a template for new environments.
- All containers start automatically without requiring `--profile` flags.

---

## 🐳 Docker Command Cheat Sheet

### 🟢 1. Starting & Stopping
* **Start everything in the background:**
  `docker compose up -d`
* **Stop everything (keeps database data):**
  `docker compose down`
* **Stop everything AND delete database data (Fresh start):**
  `docker compose down -v`
* **Rebuild containers (Run after pip installs):**
  `docker compose up --build -d`

### 🔎 2. Viewing Logs
* **View logs for all containers:**
  `docker compose logs -f`
* **View logs for JUST the backend:**
  `docker compose logs -f backend`
* **View logs for JUST the database:**
  `docker compose logs -f db`

### 💻 3. Running Commands Inside the Container
* **Open a terminal/shell inside the backend:**
  `docker compose exec backend /bin/bash`
* **Run a Django command (like migrations):**
  `docker compose exec backend python manage.py migrate`
* **Create a Django Superuser:**
  `docker compose exec backend python manage.py createsuperuser`
* **Open the Django interactive shell:**
  `docker compose exec backend python manage.py shell`

### 🧹 4. System Cleanup
* **Remove unused containers, networks, and images:**
  `docker system prune`
* **Remove absolutely EVERYTHING (deep clean):**
  `docker system prune -a --volumes`

---

## 📊 Monitoring (Grafana & Loki)

The PLG stack (Promtail + Loki + Grafana) is integrated into Docker Compose for centralized log monitoring.

### 1. Access Grafana
Navigate to `http://localhost:4000` and log in with the default credentials:
- **Username:** `admin`
- **Password:** `admin`

### 2. Connect Loki (First-Time Setup)
1. On the left sidebar, go to **Connections > Data Sources**.
2. Click **Add new data source** and select **Loki**.
3. Under the HTTP section, set the URL to: `http://loki:3100` (Docker automatically resolves this container name).
4. Scroll to the bottom and click **Save & test**.

### 3. Querying Logs
1. Go to the **Explore** tab (Compass icon on the left sidebar).
2. Ensure **Loki** is selected in the top-left dropdown.
3. Use the "Label filters" button to filter your logs. For example, to view only Django requests, set the filter to:
   `compose_service` `=` `backend`
4. Click **Run query** to stream your logs in real-time!

---

