#!/bin/bash

# Function to display usage information
show_help() {
    echo "Usage: $0 [OPTION]"
    echo "Manage Docker services for the Laguna AI Line Balancing platform."
    echo
    echo "Options:"
    echo "  --update         Rebuild Laguna backend image and start services"
    echo "  --update-all     Rebuild all images and start services"
    echo "  --down           Stop and remove all services"
    echo "  --staged         Enable staged startup sequence (recommended for production)"
    echo "  --fast           Disable staged startup sequence (recommended for development)"
    echo "  --local          Start Django dev server locally (no Docker)"
    echo "  --migrate        Run database migrations"
    echo "  --makemigrations Create new migration files"
    echo "  --shell          Open Django interactive shell"
    echo "  --superuser      Create a Django superuser"
    echo "  --test           Run the test suite"
    echo "  --backup         Backup PostgreSQL database"
    echo "  --restore FILE   Restore database from a backup file"
    echo "  -h, --help       Display this help message"
    echo
    echo "Examples:"
    echo "  $0                      # Start or restart all services (staged)"
    echo "  $0 --fast               # Quick start without staged startup"
    echo "  $0 --down               # Stop and remove all services"
    echo "  $0 --update             # Rebuild backend and start services"
    echo "  $0 --local              # Run Django locally without Docker"
    echo "  $0 --migrate            # Run Django migrations"
    echo
    echo "If no option is provided, the script will start or restart services with current images."
}

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${PROJECT_ROOT}/backend"

# Function to determine Docker Compose command
determine_docker_compose_command() {
    if command -v docker compose &>/dev/null; then
        echo "docker compose"
    elif command -v docker-compose &>/dev/null; then
        echo "docker-compose"
    else
        echo "Docker Compose is not installed." >&2
        exit 1
    fi
}

# Function to load environment variables
initialize_env() {
    if [ -f "${PROJECT_ROOT}/.env" ]; then
        echo "Loading environment variables from ${PROJECT_ROOT}/.env"
        set -a
        source "${PROJECT_ROOT}/.env"
        set +a
    elif [ -f "${PROJECT_ROOT}/.env.example" ]; then
        echo "No .env file found. Copying .env.example → .env"
        cp "${PROJECT_ROOT}/.env.example" "${PROJECT_ROOT}/.env"
        set -a
        source "${PROJECT_ROOT}/.env"
        set +a
        echo "Please review and update ${PROJECT_ROOT}/.env with your settings."
    else
        echo "Warning: .env file not found. Using defaults."
    fi

    # Determine if we're in dev mode
    if [ -n "$ENVIRONMENT" ] && [ "$ENVIRONMENT" = "development" ]; then
        export DEV_MODE=true
        echo "Running in development mode"
    else
        export DEV_MODE=false
    fi
}

# Function to check Docker is available
check_docker() {
    if ! command -v docker &>/dev/null; then
        echo "Error: Docker is not installed."
        exit 1
    fi
    if ! docker info &>/dev/null 2>&1; then
        echo "Error: Docker daemon is not running. Please start Docker Desktop."
        exit 1
    fi
    echo "Docker is available."
}

# Function to check Python is available
check_python() {
    if command -v python3 &>/dev/null; then
        PYTHON_CMD="python3"
    elif command -v python &>/dev/null; then
        PYTHON_CMD="python"
    else
        echo "Error: Python is not installed."
        exit 1
    fi
    echo "Python: $($PYTHON_CMD --version)"
}

# Function to activate virtual environment
activate_venv() {
    local venv_dir="${PROJECT_ROOT}/.venv"
    if [ -d "$venv_dir" ]; then
        echo "Activating virtual environment..."
        source "${venv_dir}/bin/activate" 2>/dev/null || source "${venv_dir}/Scripts/activate" 2>/dev/null || true
    else
        echo "Warning: No .venv found at ${venv_dir}. Using system Python."
    fi
}

# Function to remove all project-related Docker images
remove_project_images() {
    echo "Removing all local Docker images for current project..."
    $DOCKER_COMPOSE_CMD --profile dev --profile prod config | grep 'image:' | awk '{ print $2 }' | sort | uniq | xargs -r docker rmi
}

# Function to remove only Laguna backend Docker images
remove_backend_images() {
    echo "Removing Laguna backend Docker images..."
    $DOCKER_COMPOSE_CMD --profile dev --profile prod images -q backend backend_prod 2>/dev/null | xargs -r docker rmi || true
}

# Function to start services quickly (development mode)
start_services_quick() {
    echo "Starting Docker Compose services (quick mode)..."
    $DOCKER_COMPOSE_CMD -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml up --force-recreate -d
    if [ $? -ne 0 ]; then
        echo "Failed to start services."
        exit 1
    fi
    echo "All services started."
}

# Function to start services gracefully (production mode)
start_services_staged() {
    echo "Starting services in staged sequence..."

    # Stage 1: Core Infrastructure
    echo "Stage 1: Starting databases and cache (db, redis)..."
    $DOCKER_COMPOSE_CMD up --force-recreate -d db redis
    echo "Waiting for databases to initialize..."
    sleep 10

    # Stage 2: Backend Application (dev)
    echo "Stage 2: Starting dev backend (Django runserver)..."
    $DOCKER_COMPOSE_CMD -f docker-compose.yml -f docker-compose.override.yml up --force-recreate -d backend
    sleep 5

    # Stage 3: Backend Application (prod)
    echo "Stage 3: Starting prod backend (gunicorn)..."
    $DOCKER_COMPOSE_CMD -f docker-compose.yml -f docker-compose.prod.yml up --force-recreate -d backend
    sleep 5

    # Stage 4: Background Workers
    echo "Stage 4: Starting background workers (celery)..."
    $DOCKER_COMPOSE_CMD -f docker-compose.yml -f docker-compose.prod.yml up --force-recreate -d celery
    sleep 3

    # Stage 5: Developer Tools
    echo "Stage 5: Starting developer tools (pgadmin)..."
    $DOCKER_COMPOSE_CMD -f docker-compose.yml -f docker-compose.override.yml up --force-recreate -d pgadmin

    # Stage 6: Reverse Proxy
    echo "Stage 6: Starting reverse proxy (nginx)..."
    $DOCKER_COMPOSE_CMD -f docker-compose.yml -f docker-compose.prod.yml up --force-recreate -d nginx
    sleep 3

    echo "All services started successfully."
}

# Function to stop services
stop_services() {
    echo "Stopping Docker Compose services..."
    $DOCKER_COMPOSE_CMD --profile dev --profile prod --profile scheduler stop
    echo "Removing stopped containers..."
    $DOCKER_COMPOSE_CMD --profile dev --profile prod --profile scheduler rm -f
}

# Function to backup database
backup_database() {
    local backup_file="${PROJECT_ROOT}/backup_$(date +%Y%m%d_%H%M%S).sql"
    echo "Backing up database..."
    $DOCKER_COMPOSE_CMD exec -T db pg_dump -U "${DB_USER:-postgres}" "${DB_NAME:-Laguna}" > "$backup_file"
    echo "Backup saved to ${backup_file}"
}

# Function to restore database
restore_database() {
    local backup_file="$1"
    if [ -z "$backup_file" ]; then
        echo "Error: Backup file path not provided."
        echo "Usage: $0 --restore <backup-file.sql>"
        exit 1
    fi
    if [ ! -f "$backup_file" ]; then
        echo "Error: File not found: ${backup_file}"
        exit 1
    fi

    echo "Restoring database from ${backup_file}..."
    $DOCKER_COMPOSE_CMD exec -T db psql -U "${DB_USER:-postgres}" "${DB_NAME:-Laguna}" < "$backup_file"
    echo "Database restored."
}

# Set the Docker Compose command
DOCKER_COMPOSE_CMD=$(determine_docker_compose_command)

# Parse command line arguments
STAGED_MODE=true  # Default to true
COMMAND=""
RESTORE_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --staged)
            STAGED_MODE=true
            ;;
        --fast)
            STAGED_MODE=false
            ;;
        --update|--update-all|--down)
            COMMAND="$1"
            ;;
        --local|--migrate|--makemigrations|--shell|--superuser|--test|--backup)
            COMMAND="$1"
            ;;
        --restore)
            COMMAND="--restore"
            RESTORE_FILE="$2"
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
    shift
done

# Initialize environment
initialize_env

export COMPOSE_FILE="docker-compose.yml"

# Handle --down command early (before other setup)
if [ "$COMMAND" = "--down" ]; then
    echo "Stopping and removing all platform containers..."
    $DOCKER_COMPOSE_CMD -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml down
    exit 0
fi

# Handle local commands (no Docker required)
case "$COMMAND" in
    --local)
        check_python
        activate_venv
        echo "Starting Django development server..."
        echo ""
        echo "  Server:   http://127.0.0.1:8000"
        echo "  Swagger:  http://127.0.0.1:8000/swagger/"
        echo "  Redoc:    http://127.0.0.1:8000/redoc/"
        echo ""
        cd "$BACKEND_DIR"
        $PYTHON_CMD manage.py runserver
        exit 0
        ;;
    --migrate)
        check_python
        activate_venv
        echo "Running database migrations..."
        cd "$BACKEND_DIR"
        $PYTHON_CMD manage.py migrate
        echo "Migrations applied."
        exit 0
        ;;
    --makemigrations)
        check_python
        activate_venv
        echo "Creating migration files..."
        cd "$BACKEND_DIR"
        $PYTHON_CMD manage.py makemigrations
        echo "Migration files created."
        exit 0
        ;;
    --shell)
        check_python
        activate_venv
        cd "$BACKEND_DIR"
        $PYTHON_CMD manage.py shell
        exit 0
        ;;
    --superuser)
        check_python
        activate_venv
        echo "Creating superuser..."
        cd "$BACKEND_DIR"
        $PYTHON_CMD manage.py createsuperuser
        exit 0
        ;;
    --test)
        check_python
        activate_venv
        echo "Running test suite..."
        cd "$BACKEND_DIR"
        pytest --cov=. --cov-report=term-missing
        echo "Tests complete."
        exit 0
        ;;
    --backup)
        backup_database
        exit 0
        ;;
    --restore)
        restore_database "$RESTORE_FILE"
        exit 0
        ;;
esac

# Docker commands require Docker to be available
check_docker

# Main logic
case "$COMMAND" in
    --update)
        stop_services
        remove_backend_images
        $DOCKER_COMPOSE_CMD build --no-cache backend
        if [ "$STAGED_MODE" = true ]; then
            start_services_staged
        else
            start_services_quick
        fi
        ;;
    --update-all)
        stop_services
        remove_project_images
        $DOCKER_COMPOSE_CMD build --no-cache
        if [ "$STAGED_MODE" = true ]; then
            start_services_staged
        else
            start_services_quick
        fi
        ;;
    "")
        # Default behavior when no command is provided
        if $DOCKER_COMPOSE_CMD ps | grep -q "Up\|running"; then
            echo "Restarting Docker Compose services..."
            $DOCKER_COMPOSE_CMD --profile dev --profile prod restart
        else
            if [ "$STAGED_MODE" = true ]; then
                start_services_staged
            else
                start_services_quick
            fi
        fi
        ;;
esac

# Show final status
echo ""
echo "Container status:"
$DOCKER_COMPOSE_CMD --profile dev --profile prod ps -a
echo ""
echo "Access points:"
echo "  Backend:      http://localhost:${BACKEND_PORT:-8000}"
echo "  Swagger UI:   http://localhost:${BACKEND_PORT:-8000}/swagger/"
echo "  Redoc:        http://localhost:${BACKEND_PORT:-8000}/redoc/"
echo "  pgAdmin:      http://localhost:${PGADMIN_PORT:-5050}"
echo "  Redis UI:     http://localhost:8082"
echo "  Grafana:      http://localhost:4000"
echo ""
