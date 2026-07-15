# Operations Runbook: Laguna-AI Line Balancing

This runbook provides standardized procedures for DevOps and Engineering teams to troubleshoot, monitor, and recover the Laguna-AI Line Balancing production system.

---

## 1. System Monitoring & Logs

### Viewing Live Logs
All services are containerized. To view real-time logs for a specific service:

```bash
# View main Django backend logs
docker-compose logs -f backend

# View Celery worker logs (for ML and background tasks)
docker-compose logs -f celery

# View Nginx access/error logs
docker-compose logs -f nginx
```

### Inspecting Django Error Files
If the backend crashes with a 500 error, detailed stack traces are saved to persistent volumes.
```bash
# Exec into the backend container
docker-compose exec backend sh

# View the last 100 lines of the error log
tail -n 100 logs/error.log
```

---

## 2. Managing Background Tasks (Celery & Redis)

If the background tasks (Data Engine imports, Absenteeism predictions, Manning Sheet calculations) appear "stuck" or are not processing:

### Check Celery Worker Status
```bash
# Ping the celery worker to see if it is responsive
docker-compose exec backend celery -A config inspect ping
```

### Check Redis Queue Length
If workers are overwhelmed, tasks will pile up in Redis.
```bash
# Access the Redis CLI
docker-compose exec redis redis-cli

# Check the length of the default Celery queue
127.0.0.1:6379> LLEN celery
```
*If the queue length is unusually high (e.g., > 10,000) and not decreasing, restart the Celery worker.*

### Restarting a Stuck Worker
```bash
docker-compose restart celery
```
*Note: Restarting the worker will not lose pending tasks, as they remain safely in the Redis broker queue until explicitly acknowledged.*

---

## 3. Database Operations

### Backing Up the Database
To create a manual backup of the PostgreSQL database without bringing down the system:
```bash
# Create a backup file on the host machine
docker-compose exec -t db pg_dump -U $DB_USER $DB_NAME -c > backup_$(date +%F).sql
```

### Restoring the Database
*Warning: This is a destructive operation that will overwrite current data.*
```bash
cat backup_YYYY-MM-DD.sql | docker-compose exec -T db psql -U $DB_USER -d $DB_NAME
```

---

## 4. Emergency Procedures

### Full System Restart
If the entire application becomes unresponsive (e.g., 502 Bad Gateway across all endpoints) and restarting individual services fails:

```bash
# Gracefully stop all containers
docker-compose down

# Restart the system in detached mode
docker-compose up -d
```

### Database Lock / Deadlock
If the system logs show PostgreSQL deadlock errors (`OperationalError: deadlock detected`), restart the database container to terminate all connections:
```bash
docker-compose restart db
```
*Note: The backend and celery containers are configured to automatically reconnect once the database is healthy.*
