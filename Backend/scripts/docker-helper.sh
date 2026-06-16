#!/bin/bash

# Docker Compose Helper Script for Laguna AI Backend
# Usage: ./docker-helper.sh [command]

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Functions
show_help() {
    echo -e "${BLUE}Laguna AI - Docker Helper${NC}"
    echo ""
    echo "Usage: ./docker-helper.sh [command]"
    echo ""
    echo "Commands:"
    echo "  ${GREEN}start${NC}          - Start all services"
    echo "  ${GREEN}stop${NC}           - Stop all services"
    echo "  ${GREEN}restart${NC}        - Restart all services"
    echo "  ${GREEN}logs${NC}           - Show logs for all services"
    echo "  ${GREEN}shell${NC}          - Open Django shell"
    echo "  ${GREEN}migrate${NC}        - Run database migrations"
    echo "  ${GREEN}makemigrations${NC} - Create new migrations"
    echo "  ${GREEN}superuser${NC}      - Create superuser"
    echo "  ${GREEN}test${NC}           - Run tests"
    echo "  ${GREEN}clean${NC}          - Remove all containers and volumes"
    echo "  ${GREEN}backup${NC}         - Backup database"
    echo "  ${GREEN}restore${NC}        - Restore database from backup"
    echo "  ${GREEN}status${NC}         - Show container status"
    echo "  ${GREEN}rebuild${NC}        - Rebuild Docker images"
    echo ""
}

start() {
    echo -e "${BLUE}Starting services...${NC}"
    docker-compose up -d
    echo -e "${GREEN}✓ Services started${NC}"
    status
}

stop() {
    echo -e "${BLUE}Stopping services...${NC}"
    docker-compose stop
    echo -e "${GREEN}✓ Services stopped${NC}"
}

restart() {
    echo -e "${BLUE}Restarting services...${NC}"
    docker-compose restart
    echo -e "${GREEN}✓ Services restarted${NC}"
}

logs() {
    docker-compose logs -f
}

shell() {
    echo -e "${BLUE}Opening Django shell...${NC}"
    docker-compose exec backend python manage.py shell
}

migrate() {
    echo -e "${BLUE}Running migrations...${NC}"
    docker-compose exec backend python manage.py migrate
    echo -e "${GREEN}✓ Migrations complete${NC}"
}

makemigrations() {
    echo -e "${BLUE}Creating migrations...${NC}"
    docker-compose exec backend python manage.py makemigrations
    echo -e "${GREEN}✓ Migrations created${NC}"
}

superuser() {
    echo -e "${BLUE}Creating superuser...${NC}"
    docker-compose exec backend python manage.py createsuperuser
}

test() {
    echo -e "${BLUE}Running tests...${NC}"
    docker-compose exec backend python manage.py test
}

clean() {
    echo -e "${RED}Warning: This will remove all containers, networks, and volumes${NC}"
    read -p "Continue? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}Cleaning up...${NC}"
        docker-compose down -v
        echo -e "${GREEN}✓ Cleanup complete${NC}"
    fi
}

backup() {
    echo -e "${BLUE}Backing up database...${NC}"
    BACKUP_FILE="backup_$(date +%Y%m%d_%H%M%S).sql"
    docker-compose exec -T db pg_dump -U postgres Laguna > "$BACKUP_FILE"
    echo -e "${GREEN}✓ Backup saved to $BACKUP_FILE${NC}"
}

restore() {
    if [ -z "$1" ]; then
        echo -e "${RED}Error: Backup file not specified${NC}"
        echo "Usage: ./docker-helper.sh restore <backup-file>"
        exit 1
    fi
    
    if [ ! -f "$1" ]; then
        echo -e "${RED}Error: File $1 not found${NC}"
        exit 1
    fi
    
    echo -e "${BLUE}Restoring database from $1...${NC}"
    docker-compose exec -T db psql -U postgres Laguna < "$1"
    echo -e "${GREEN}✓ Database restored${NC}"
}

status() {
    echo -e "${BLUE}Container Status:${NC}"
    docker-compose ps
}

rebuild() {
    echo -e "${BLUE}Rebuilding images...${NC}"
    docker-compose build --no-cache
    echo -e "${GREEN}✓ Images rebuilt${NC}"
}

# Main
if [ $# -eq 0 ]; then
    show_help
    exit 0
fi

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    logs)
        logs
        ;;
    shell)
        shell
        ;;
    migrate)
        migrate
        ;;
    makemigrations)
        makemigrations
        ;;
    superuser)
        superuser
        ;;
    test)
        test
        ;;
    clean)
        clean
        ;;
    backup)
        backup
        ;;
    restore)
        restore "$2"
        ;;
    status)
        status
        ;;
    rebuild)
        rebuild
        ;;
    help|-h|--help)
        show_help
        ;;
    *)
        echo -e "${RED}Unknown command: $1${NC}"
        show_help
        exit 1
        ;;
esac
