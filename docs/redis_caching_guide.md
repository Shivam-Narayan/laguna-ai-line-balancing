# Redis Caching & Redis Commander Guide

This guide explains how Redis is implemented in the Laguna backend for both Caching and Celery task management, as well as how to visually monitor it using Redis Commander.

## 1. Infrastructure Overview

The project uses two docker containers for Redis:
- **`redis`**: The actual database engine storing the key-value data in memory (Port `6379`).
- **`redis-commander`**: A web-based graphical user interface (GUI) to view and manage the data inside the `redis` container (Mapped to port `8082` locally).

### Starting the Infrastructure
To start the Redis database and the Redis Commander UI, run:
```bash
docker compose up -d
```
You can access the UI at **http://localhost:8082**.

---

## 2. Django Configuration Setup

For Django to talk to Redis, it requires the `django-redis` package. The configuration must be set in your settings file (e.g., `config/settings/development.py` and `config/settings/production.py`).

**Required Settings:**
```python
import os

# Define the Redis URL
REDIS_BACKEND = os.getenv("REDIS_BACKEND", "redis://127.0.0.1:6379/0")

# 1. Configure Celery to use Redis as the message broker
CELERY_BROKER_URL = REDIS_BACKEND

# 2. Configure Django Caching to use Redis
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_BACKEND,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "CONNECTION_POOL_KWARGS": {"max_connections": 100},
        }
    }
}
```

> [!WARNING]
> If the `CACHES` dictionary is missing from your environment's settings file, Django will silently fall back to `LocMemCache` (local memory), meaning the cache will not appear in Redis Commander and will be wiped every time the server restarts.

---

## 3. How to Cache Data (End to End)

To cache data manually in your service layer, follow this pattern:

```python
from django.core.cache import cache

def get_heavy_data(param):
    # 1. Define a unique cache key
    cache_key = f"heavy_data_key_{param}"
    
    # 2. Check if it exists in Redis
    cached_data = cache.get(cache_key)
    
    # 3. Cache Hit: Return immediately
    if cached_data is not None:
        return cached_data
        
    # 4. Cache Miss: Do the heavy database/pandas calculations
    calculated_data = execute_heavy_database_query(param)
    
    # 5. Save it to Redis. timeout is in seconds (43200 = 12 hours)
    cache.set(cache_key, calculated_data, timeout=43200)
    
    return calculated_data
```

### Viewing Cached Data in Redis Commander
When Django caches Python dictionaries, it serializes them using `pickle`. When viewing this data in Redis Commander:
- The key will be prefixed with `:1:` (e.g., `:1:heavy_data_key_X`).
- The data type will show as **String (Binary)**.
- The value will appear to have strange characters around the text. This is normal Python pickle formatting.

---

## 4. Cache Invalidation (Preventing Stale Data)

If the underlying database tables are updated, you **must** invalidate the cache so users don't see old data. 

To clear multiple keys at once, use `delete_many()`:
```python
from django.core.cache import cache

def generate_new_data():
    # ... logic that updates the database ...
    
    # Invalidate the cache
    keys_to_delete = ["heavy_data_key_A", "heavy_data_key_B"]
    cache.delete_many(keys_to_delete)
```

---

## 5. Important Note on Celery Keys

When you look in Redis Commander, you will see folders like:
- `_kombu.binding.celery`
- `_kombu.binding.celery.pidbox`
- `_kombu.binding.celeryev`

> [!CAUTION]
> **DO NOT DELETE THESE KEYS.** 
> These are system keys created by Celery and its messaging library (Kombu). Celery uses these to queue background tasks (like D-Day generation or Excel uploads) and track worker statuses. Deleting them can cause background tasks to fail or hang.

---

## 6. Helpful Terminal Commands

If you ever need to interact with Redis from the terminal without the GUI, use these commands:

### Testing Cache Injection (Django Shell)
You can inject a test key into Redis directly from your Django environment:
```bash
python manage.py shell -c "from django.core.cache import cache; cache.set('hello_world', {'message': 'Testing!'}, timeout=3600); print('Injected!')"
```

### Viewing Logs
To see if Redis or Redis Commander is throwing errors:
```bash
# View Redis database logs
docker logs laguna-ai-line-balancing-redis-1 -f

# View Redis Commander logs
docker logs laguna-ai-line-balancing-redis-commander-1 -f
```

### Direct Database Access (redis-cli)
If you want to manually run Redis commands (like `FLUSHALL`) directly inside the docker container:
```bash
# 1. Enter the redis container
docker exec -it laguna-ai-line-balancing-redis-1 redis-cli

# 2. View all keys
KEYS *

# 3. Nuke everything (DANGEROUS)
FLUSHALL
```
