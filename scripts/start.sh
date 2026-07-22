#!/bin/bash
# ============================================================================
# Laguna AI Line Balancing — Startup Script (Linux/Mac Bash)
# ============================================================================
# Usage: scripts/start.sh [OPTION]
# Run with -h or --help for details.
# ============================================================================

# ── Project root (one level up from scripts/) ─────────────────────────────
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${PROJECT_ROOT}/backend"
ENV_FILE="${PROJECT_ROOT}/.env"

# ── Parse arguments ───────────────────────────────────────────────────────
COMMAND=""
STAGED_MODE=false
RESTORE_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --staged)         STAGED_MODE=true; shift ;;
        --fast)           STAGED_MODE=false; shift ;;
        --dev)            COMMAND="dev"; shift ;;
        --prod)           COMMAND="prod"; shift ;;
        --build)          COMMAND="build"; shift ;;
        --down)           COMMAND="down"; shift ;;
        --clean)          COMMAND="clean"; shift ;;
        --logs)           COMMAND="logs"; shift ;;
        --status)         COMMAND="status"; shift ;;
        --local)          COMMAND="local"; shift ;;
        --migrate)        COMMAND="migrate"; shift ;;
        --makemigrations) COMMAND="makemigrations"; shift ;;
        --shell)          COMMAND="shell"; shift ;;
        --superuser)      COMMAND="superuser"; shift ;;
        --test)           COMMAND="test"; shift ;;
        --backup)         COMMAND="backup"; shift ;;
        --restore)        COMMAND="restore"; RESTORE_FILE="$2"; shift 2 ;;
        -h|--help)        COMMAND="help"; shift ;;
        *)                echo "[ERROR] Unknown option: $1"; COMMAND="help"; break ;;
    esac
done

# ── Functions ─────────────────────────────────────────────────────────────
show_banner() {
    echo ""
    echo "  ======================================================"
    echo "       Laguna AI  -  Line Balancing Platform"
    echo "  ======================================================"
    echo ""
}

show_help() {
    show_banner
    echo "Usage: scripts/start.sh [OPTION]"
    echo ""
    echo "Docker Commands:"
    echo "  --dev              Start development services  (db + redis + backend + app + pgadmin)"
    echo "  --prod             Start production services   (db + redis + backend + app + celery + scheduler + nginx)"
    echo "  --build            Rebuild Docker images and start dev services"
    echo "  --down             Stop and remove all containers"
    echo "  --clean            Stop, remove containers, and delete volumes (WARNING: Data Loss)"
    echo "  --logs             Follow log output for all services"
    echo "  --status           Show status of all running containers"
    echo ""
    echo "Local Django Commands (Requires local Python env):"
    echo "  --local            Start Django dev server locally (no Docker)"
    echo "  --migrate          Run database migrations locally"
    echo "  --makemigrations   Create new migration files locally"
    echo "  --shell            Open Django interactive shell locally"
    echo "  --superuser        Create a Django superuser locally"
    echo "  --test             Run the pytest suite locally"
    echo ""
    echo "Database Commands:"
    echo "  --backup           Backup PostgreSQL database to a .sql file"
    echo "  --restore <file>   Restore database from a backup file"
    echo ""
    exit 0
}

load_env() {
    if [ -f "$ENV_FILE" ]; then
        set -a
        source "$ENV_FILE"
        set +a
    elif [ -f "${PROJECT_ROOT}/.env.example" ]; then
        echo "[WARN] No .env file found. Copying .env.example to .env"
        cp "${PROJECT_ROOT}/.env.example" "$ENV_FILE"
        set -a
        source "$ENV_FILE"
        set +a
    else
        echo "[WARN] No .env file found. Using defaults."
    fi
}

check_docker() {
    if ! command -v docker &>/dev/null; then
        echo "[ERROR] Docker is not installed."
        exit 1
    fi
    if ! docker info &>/dev/null 2>&1; then
        echo "[ERROR] Docker daemon is not running. Please start Docker Desktop."
        exit 1
    fi
    echo "[OK] Docker is available"
}

determine_docker_compose() {
    if command -v docker compose &>/dev/null; then
        DC="docker compose"
    elif command -v docker-compose &>/dev/null; then
        DC="docker-compose"
    else
        echo "[ERROR] Docker Compose is not installed."
        exit 1
    fi
}

# ── Script Execution ──────────────────────────────────────────────────────

if [ "$COMMAND" = "help" ]; then
    show_help
fi

show_banner

# Default command
if [ -z "$COMMAND" ]; then
    COMMAND="all"
fi

load_env

COMPOSE_FILE="docker-compose.yml"

case "$COMMAND" in
    all)
        check_docker
        determine_docker_compose
        if [ "$STAGED_MODE" = "true" ]; then
            echo "[INFO] Starting ALL services (staged sequence)..."
            echo "  Stage 1/4: Core infrastructure (db, redis)..."
            $DC -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml up -d db redis
            sleep 10
            echo "  Stage 2/4: Backend application..."
            $DC -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml up -d backend
            sleep 5
            echo "  Stage 3/4: Background workers (celery, scheduler)..."
            $DC -f docker-compose.yml -f docker-compose.prod.yml up -d celery scheduler
            sleep 3
            echo "  Stage 4/4: Developer tools and reverse proxy (pgadmin, nginx)..."
            $DC -f docker-compose.yml -f docker-compose.override.yml up -d pgadmin
            $DC -f docker-compose.yml -f docker-compose.prod.yml up -d nginx
        else
            echo "[INFO] Starting ALL services (fast mode)..."
            $DC -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml up --force-recreate -d
        fi
        
        echo "[OK] All services started"
        echo "  Dev Backend:   http://localhost:${BACKEND_PORT:-8000}"
        echo "  Swagger:       http://localhost:${BACKEND_PORT:-8000}/swagger/"
        echo "  pgAdmin:       http://localhost:${PGADMIN_PORT:-5050}"
        echo "  Redis UI:      http://localhost:8082"
        echo "  Prod (nginx):  http://localhost"
        echo "  Grafana:       http://localhost:4000"
        echo ""
        ;;
        
    dev)
        check_docker
        determine_docker_compose
        echo "[INFO] Starting DEVELOPMENT services (fast mode)..."
        $DC -f docker-compose.yml -f docker-compose.override.yml up --force-recreate -d
        echo "[OK] Dev services started"
        echo "  Dev Backend:   http://localhost:${BACKEND_PORT:-8000}"
        echo "  Swagger:       http://localhost:${BACKEND_PORT:-8000}/swagger/"
        echo "  pgAdmin:       http://localhost:${PGADMIN_PORT:-5050}"
        echo "  Redis UI:      http://localhost:8082"
        echo "  Grafana:       http://localhost:4000"
        echo ""
        ;;
        
    prod)
        check_docker
        determine_docker_compose
        echo "[INFO] Starting PRODUCTION services (staged sequence)..."
        echo "  Stage 1/3: Core infrastructure..."
        $DC -f docker-compose.yml -f docker-compose.prod.yml up -d db redis
        sleep 10
        echo "  Stage 2/3: Application and workers..."
        $DC -f docker-compose.yml -f docker-compose.prod.yml up -d backend celery scheduler
        sleep 5
        echo "  Stage 3/3: Reverse proxy..."
        $DC -f docker-compose.yml -f docker-compose.prod.yml up -d nginx
        echo "[OK] Prod services started"
        echo "  Prod (nginx):  http://localhost"
        echo "  Grafana:       http://localhost:4000"
        echo ""
        ;;
        
    build)
        check_docker
        determine_docker_compose
        echo "[INFO] Rebuilding Docker images and starting dev services..."
        $DC -f docker-compose.yml -f docker-compose.override.yml down
        $DC -f docker-compose.yml -f docker-compose.override.yml build
        $DC -f docker-compose.yml -f docker-compose.override.yml up -d
        echo "[OK] Rebuild complete"
        ;;
        
    down)
        check_docker
        determine_docker_compose
        echo "[INFO] Stopping and removing containers..."
        $DC -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml down
        echo "[OK] Containers stopped"
        ;;
        
    clean)
        check_docker
        determine_docker_compose
        echo "[WARN] Destructive action initiated"
        echo "       This will delete all containers and volumes (data loss)."
        read -p "       Are you sure you want to continue? (y/N) " confirm
        if [[ $confirm == [yY] || $confirm == [yY][eE][sS] ]]; then
            $DC -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml down -v
            echo "[OK] Cleaned all containers and volumes"
        else
            echo "[INFO] Aborted"
        fi
        ;;
        
    logs)
        check_docker
        determine_docker_compose
        $DC -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml logs -f
        ;;
        
    status)
        check_docker
        determine_docker_compose
        $DC -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml ps
        ;;
        
    *)
        # Commands requiring python
        if ! command -v python3 &>/dev/null; then
            if ! command -v python &>/dev/null; then
                echo "[ERROR] Python is not installed."
                exit 1
            fi
            PYTHON_CMD="python"
        else
            PYTHON_CMD="python3"
        fi
        
        venv_dir="${PROJECT_ROOT}/.venv"
        if [ -d "$venv_dir" ]; then
            source "${venv_dir}/bin/activate" 2>/dev/null || source "${venv_dir}/Scripts/activate" 2>/dev/null || true
        fi
        
        cd "$BACKEND_DIR" || exit 1
        
        if [ "$COMMAND" = "local" ]; then
            echo "[INFO] Starting local Django dev server..."
            $PYTHON_CMD manage.py runserver
        elif [ "$COMMAND" = "migrate" ]; then
            echo "[INFO] Running database migrations..."
            $PYTHON_CMD manage.py migrate
        elif [ "$COMMAND" = "makemigrations" ]; then
            echo "[INFO] Creating migration files..."
            $PYTHON_CMD manage.py makemigrations
        elif [ "$COMMAND" = "shell" ]; then
            $PYTHON_CMD manage.py shell
        elif [ "$COMMAND" = "superuser" ]; then
            $PYTHON_CMD manage.py createsuperuser
        elif [ "$COMMAND" = "test" ]; then
            echo "[INFO] Running test suite..."
            pytest --cov=. --cov-report=term-missing
        elif [ "$COMMAND" = "backup" ]; then
            check_docker
            determine_docker_compose
            cd "$PROJECT_ROOT"
            backup_file="${PROJECT_ROOT}/backup_$(date +%Y%m%d_%H%M%S).sql"
            echo "[INFO] Backing up database..."
            $DC exec -T db pg_dump -U "${DB_USER:-postgres}" "${DB_NAME:-Laguna}" > "$backup_file"
            echo "[OK] Backup saved to ${backup_file}"
        elif [ "$COMMAND" = "restore" ]; then
            check_docker
            determine_docker_compose
            cd "$PROJECT_ROOT"
            if [ -z "$RESTORE_FILE" ]; then
                echo "[ERROR] Backup file path not provided."
                exit 1
            fi
            if [ ! -f "$RESTORE_FILE" ]; then
                echo "[ERROR] File not found: ${RESTORE_FILE}"
                exit 1
            fi
            echo "[INFO] Restoring database from ${RESTORE_FILE}..."
            $DC exec -T db psql -U "${DB_USER:-postgres}" "${DB_NAME:-Laguna}" < "$RESTORE_FILE"
            echo "[OK] Database restored."
        fi
        ;;
esac
