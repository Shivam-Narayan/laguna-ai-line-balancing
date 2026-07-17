# Operations Runbook: Laguna-AI Line Balancing

This runbook provides standardized procedures for DevOps and Engineering teams to troubleshoot, monitor, and recover the Laguna-AI Line Balancing production system.

---

## 1. System Monitoring & Logs

### Viewing Live Logs
All services are containerized. To view real-time logs for a specific service:

```bash
# View main Django backend logs
./scripts/start.sh --logs backend

# View Celery worker logs (for ML and background tasks)
./scripts/start.sh --logs celery

# View Nginx access/error logs
./scripts/start.sh --logs nginx
```

### Inspecting Django Error Files
If the backend crashes with a 500 error, detailed stack traces are saved to persistent volumes.
```bash
# Exec into the backend container (requires raw docker compose with correct files, or just use docker exec)
docker exec -it laguna-ai-line-balancing-backend-1 sh

# View the last 100 lines of the error log
tail -n 100 logs/error.log
```

---

## 2. Managing Background Tasks (Celery & Redis)

If the background tasks (Data Engine imports, Absenteeism predictions, Manning Sheet calculations) appear "stuck" or are not processing:

### Check Celery Worker Status
```bash
# Ping the celery worker to see if it is responsive
docker exec -it laguna-ai-line-balancing-backend-1 celery -A config inspect ping
```

### Check Redis Queue Length
If workers are overwhelmed, tasks will pile up in Redis.
```bash
# Access the Redis CLI
docker exec -it laguna-ai-line-balancing-redis-1 redis-cli

# Check the length of the default Celery queue
127.0.0.1:6379> LLEN celery
```
*If the queue length is unusually high (e.g., > 10,000) and not decreasing, restart the Celery worker.*

### Restarting a Stuck Worker
```bash
docker restart laguna-ai-line-balancing-celery-1
```
*Note: Restarting the worker will not lose pending tasks, as they remain safely in the Redis broker queue until explicitly acknowledged.*

---

## 3. Database Operations

### Backing Up the Database
To create a manual backup of the PostgreSQL database without bringing down the system:
```bash
# Create a backup file on the host machine using the helper script
./scripts/start.sh --backup
```

### Restoring the Database
*Warning: This is a destructive operation that will overwrite current data.*
```bash
# Restore from a SQL backup file
./scripts/start.sh --restore backup_YYYY-MM-DD.sql
```

---

## 4. Emergency Procedures

### Full System Restart
If the entire application becomes unresponsive (e.g., 502 Bad Gateway across all endpoints) and restarting individual services fails:

```bash
# Gracefully stop all containers
./scripts/start.sh --down

# Restart the system
./scripts/start.sh --prod   # or --dev
```

### Database Lock / Deadlock
If the system logs show PostgreSQL deadlock errors (`OperationalError: deadlock detected`), restart the database container to terminate all connections:
```bash
docker restart laguna-ai-line-balancing-db-1
```
*Note: The backend and celery containers are configured to automatically reconnect once the database is healthy.*
