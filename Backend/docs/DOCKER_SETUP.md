# Docker Setup for Laguna AI Line Balancing

This guide explains how to run the entire Laguna AI application using Docker Compose.

## 📋 Prerequisites

- Docker Desktop installed ([Download](https://www.docker.com/products/docker-desktop))
- Docker Compose (included with Docker Desktop)

## 🚀 Quick Start

### 1. Setup Environment Variables

```bash
# Copy the docker environment template
cp .env.docker .env.docker.local

# Edit with your configuration
# nano .env.docker.local  # or use your editor
```

### 2. Start the Application

```bash
# Start all services (backend, database, redis)
docker-compose up -d

# OR with custom env file
docker-compose --env-file .env.docker.local up -d
```

### 3. Run Migrations

```bash
# Create database tables
docker-compose exec backend python manage.py migrate

# Create superuser for admin
docker-compose exec backend python manage.py createsuperuser
```

### 4. Access the Application

- **Django Backend**: http://localhost:8000
- **Django Admin**: http://localhost:8000/admin
- **Database**: localhost:5432
- **Redis**: localhost:6379

## 📦 Services

### Backend (Django)
- Python 3.11 Django 5.1
- Runs on port 8000
- Auto-reloads on code changes (development mode)
- Connected to PostgreSQL and Redis

### Database (PostgreSQL)
- PostgreSQL 15
- Default credentials: postgres/postgres
- Persistent volume: `postgres_data`
- Port: 5432

### Cache (Redis)
- Redis 7
- Used for caching and background jobs
- Port: 6379
- Persistent volume: `redis_data`

## 🎮 Common Commands

### View Logs
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f backend
docker-compose logs -f db
docker-compose logs -f redis
```

### Execute Commands in Container
```bash
# Django shell
docker-compose exec backend python manage.py shell

# Run migrations
docker-compose exec backend python manage.py migrate

# Create superuser
docker-compose exec backend python manage.py createsuperuser

# Run tests
docker-compose exec backend python manage.py test

# Collect static files
docker-compose exec backend python manage.py collectstatic --noinput
```

### Database Management
```bash
# Access PostgreSQL
docker-compose exec db psql -U postgres -d Laguna

# Backup database
docker-compose exec db pg_dump -U postgres Laguna > backup.sql

# Restore database
docker-compose exec -T db psql -U postgres Laguna < backup.sql
```

### Stop Services
```bash
# Stop all services (keep data)
docker-compose stop

# Stop and remove containers (keep volumes)
docker-compose down

# Stop, remove containers AND volumes
docker-compose down -v
```

## 🧹 Cleanup

```bash
# Remove all containers, networks (keep volumes)
docker-compose down

# Remove everything including volumes
docker-compose down -v

# Prune unused Docker resources
docker system prune -a
```

## 🔧 Configuration

### Environment Variables

Edit `.env.docker` or `.env.docker.local`:

```env
# Django
ENVIRONMENT=development
DEBUG=True
SECRET_KEY=your-secret-key

# Database
DB_NAME=Laguna
DB_USER=postgres
DB_PASSWORD=postgres

# Email (SendGrid)
SENDGRID_API_KEY=your-api-key
```

## 📊 Database

### Connect to PostgreSQL
```bash
# From inside container
docker-compose exec db psql -U postgres -d Laguna

# From host machine
psql -h localhost -U postgres -d Laguna
```

### Useful PostgreSQL Commands
```sql
-- List all tables
\dt

-- Describe table
\d table_name

-- List all databases
\l

-- Exit psql
\q
```

## 🚨 Troubleshooting

### Container Fails to Start
```bash
# Check logs
docker-compose logs backend

# Rebuild image
docker-compose build --no-cache

# Remove old containers
docker-compose down -v
docker-compose up -d
```

### Port Already in Use
```bash
# Change port in docker-compose.yml
# Change "8000:8000" to "8001:8000" for example
```

### Database Connection Error
```bash
# Wait for database to be ready
docker-compose up -d db
sleep 10
docker-compose up -d backend
```

### Permission Issues on Linux
```bash
# Run Docker without sudo
sudo usermod -aG docker $USER
newgrp docker
```

## 📝 Production Deployment

For production, modify docker-compose.yml:

```yaml
backend:
  command: >
    gunicorn backend_laguna.wsgi:application
    --bind 0.0.0.0:8000
    --workers 4
    --timeout 120
```

And set environment:
```bash
ENVIRONMENT=production
DEBUG=False
SECRET_KEY=your-long-secure-key
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
```

## 🔐 Security Notes

- Change `SECRET_KEY` in production
- Use strong database passwords
- Set `DEBUG=False` in production
- Use environment-specific .env files
- Never commit .env files to git

## 📚 Additional Resources

- [Docker Docs](https://docs.docker.com/)
- [Docker Compose Docs](https://docs.docker.com/compose/)
- [Django in Docker](https://docs.djangoproject.com/en/5.1/howto/deployment/wsgi/uwsgi/)

## 🤝 Support

For issues, check logs:
```bash
docker-compose logs --tail=100 backend
```
