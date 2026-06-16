# Docker Quick Reference

## 🚀 Start Developing (5 minutes)

```bash
# 1. Start all services
docker-compose up -d

# 2. Run migrations
docker-compose exec backend python manage.py migrate

# 3. Create superuser
docker-compose exec backend python manage.py createsuperuser

# 4. Open browser
# http://localhost:8000
# http://localhost:8000/admin (admin panel)
```

## 📋 Common Commands

### Service Management
```bash
docker-compose up -d              # Start all services
docker-compose down               # Stop all services
docker-compose restart            # Restart all services
docker-compose ps                 # Show running containers
docker-compose logs -f            # View logs (all services)
docker-compose logs -f backend    # View logs (specific service)
```

### Django Management
```bash
docker-compose exec backend python manage.py migrate           # Run migrations
docker-compose exec backend python manage.py createsuperuser   # Create admin user
docker-compose exec backend python manage.py shell             # Django shell
docker-compose exec backend python manage.py test              # Run tests
docker-compose exec backend python manage.py collectstatic     # Collect static files
```

### Database
```bash
docker-compose exec db psql -U postgres -d Laguna  # PostgreSQL shell
docker-compose exec -T db pg_dump -U postgres Laguna > backup.sql  # Backup
docker-compose exec -T db psql -U postgres Laguna < backup.sql     # Restore
```

### Code Changes
```bash
# Code changes auto-reload in development
# Just edit files, no restart needed

# For requirements.txt changes:
docker-compose exec backend pip install -r requirements.txt
docker-compose restart backend
```

## 🐳 Docker Compose Services

| Service | Port | Purpose |
|---------|------|---------|
| backend | 8000 | Django application |
| db | 5432 | PostgreSQL database |
| redis | 6379 | Redis cache |
| nginx* | 80/443 | Reverse proxy (prod only) |

*nginx only in docker-compose.prod.yml

## 📦 Using Helper Scripts

### Linux/Mac
```bash
chmod +x docker-helper.sh

./docker-helper.sh start          # Start services
./docker-helper.sh stop           # Stop services
./docker-helper.sh migrate        # Run migrations
./docker-helper.sh superuser      # Create superuser
./docker-helper.sh shell          # Django shell
./docker-helper.sh backup         # Backup database
./docker-helper.sh logs           # View logs
./docker-helper.sh status         # Container status
```

### Windows
```cmd
docker-helper.bat start           # Start services
docker-helper.bat stop            # Stop services
docker-helper.bat migrate         # Run migrations
docker-helper.bat superuser       # Create superuser
docker-helper.bat logs            # View logs
docker-helper.bat status          # Container status
```

## 🔧 Configuration

### Development (.env.docker)
```env
ENVIRONMENT=development
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0
```

### Production (.env.prod)
```env
ENVIRONMENT=production
DEBUG=False
SECRET_KEY=your-long-secure-key
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
```

## 🔐 Default Credentials

| Service | User | Password |
|---------|------|----------|
| PostgreSQL | postgres | postgres |
| Django Admin | (create) | (create) |

## 🧪 Testing

```bash
# Run all tests
docker-compose exec backend python manage.py test

# Run specific app tests
docker-compose exec backend python manage.py test apps.accounts

# Run with coverage
docker-compose exec backend coverage run --source='.' manage.py test
docker-compose exec backend coverage report
```

## 📊 Viewing Logs

```bash
# All services
docker-compose logs

# Follow logs (streaming)
docker-compose logs -f

# Last 100 lines
docker-compose logs --tail=100

# Specific service
docker-compose logs backend
docker-compose logs db
docker-compose logs redis
```

## 🛠️ Troubleshooting

| Issue | Solution |
|-------|----------|
| Port already in use | `docker-compose down -v` or change port in yml |
| Container won't start | `docker-compose logs [service]` to see error |
| Database connection failed | Wait 30s, then try again |
| "Permission denied" (Linux) | `sudo usermod -aG docker $USER` |
| Need to rebuild | `docker-compose build --no-cache` |

## 🧹 Cleanup

```bash
docker-compose stop              # Stop services (keep data)
docker-compose down              # Stop and remove containers
docker-compose down -v           # Remove everything including data
docker system prune -a           # Remove unused Docker resources
```

## 📁 Volume Persistence

All data automatically saved to:
- `postgres_data/` - Database
- `redis_data/` - Cache
- `static_volume/` - Static files
- `media_volume/` - User uploads
- `logs_volume/` - Application logs

To reset: `docker-compose down -v`

## 🚀 Production Deployment

```bash
# Use production compose file
docker-compose -f docker-compose.prod.yml up -d

# Or with custom env file
docker-compose -f docker-compose.prod.yml \
  --env-file .env.prod.local up -d
```

## 📚 Full Documentation

See [DOCKER_SETUP.md](./DOCKER_SETUP.md) for comprehensive guide

## 🆘 Getting Help

```bash
# Check service health
docker-compose ps

# View detailed logs
docker-compose logs [service]

# Inspect container
docker inspect [container-name]

# Get container IP
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' [container]
```

---

**Quick Links:**
- [Django Shell](#testing) - `./docker-helper.sh shell`
- [Logs](#-viewing-logs) - `docker-compose logs -f`
- [Backup](#database) - `./docker-helper.sh backup`
- [Restore](#database) - `./docker-helper.sh restore backup.sql`
