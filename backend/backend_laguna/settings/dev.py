"""
Django settings for backend_laguna project - Development Configuration
"""

from .base import *

# Development settings override
DEBUG = True

ALLOWED_HOSTS = ['127.0.0.1', 'localhost', '*']

# Development database (can override in .env)
if not os.getenv('DB_ENGINE'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
        }
    }

# Development email backend (console)
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# CORS settings for development (more permissive)
CORS_ALLOW_ALL_ORIGINS = True

# Development logging (more verbose)
LOGGING['loggers']['general']['level'] = 'DEBUG'
LOGGING['loggers']['middleware']['level'] = 'DEBUG'

# Optional: Redis cache for development
# REDIS_BACKEND = "redis://127.0.0.1:6379/0"
# CACHES = {
#     "default": {
#         "BACKEND": "django_redis.cache.RedisCache",
#         "LOCATION": REDIS_BACKEND,
#         "OPTIONS": {
#             "CLIENT_CLASS": "django_redis.client.DefaultClient",
#             "CONNECTION_POOL_KWARGS": {"max_connections": 100},
#         }
#     }
# }

# Disable cache middleware in development for easier debugging
# CACHE_MIDDLEWARE_ALIAS = 'default'
# CACHE_MIDDLEWARE_SECONDS = 10
