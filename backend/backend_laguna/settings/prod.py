"""
Django settings for backend_laguna project - Production Configuration
"""

from .base import *

# Production settings override
DEBUG = False

allowed_hosts_env = os.getenv("ALLOWED_HOSTS", "")
ALLOWED_HOSTS = allowed_hosts_env.split(",") if allowed_hosts_env else ['127.0.0.1']

# Production database (must be configured via environment variables)
DATABASES = {
    'default': {
        'ENGINE': os.getenv('DB_ENGINE', 'django.db.backends.postgresql'),
        'NAME': os.getenv('DB_NAME', 'Laguna'),
        'USER': os.getenv('DB_USER'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST'),
        'PORT': os.getenv('DB_PORT', '5432'),
        'CONN_MAX_AGE': 600,
        'OPTIONS': {
            'connect_timeout': 10,
        }
    }
}

# CORS settings for production (restricted)
CORS_ALLOWED_ORIGINS = [
    "https://yuktiai.laguna-clothing.com",
    "https://ascendumai.azurewebsites.net",
]

# Security settings for production
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_SECURITY_POLICY = {
    'default-src': ("'self'",),
    'script-src': ("'self'", "'unsafe-inline'"),
}

# Production email backend (SendGrid)
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.sendgrid.net"
EMAIL_PORT = 587
EMAIL_USE_TLS = True

# Production logging (INFO level only)
LOGGING['loggers']['general']['level'] = 'INFO'
LOGGING['loggers']['middleware']['level'] = 'INFO'

# Redis cache for production
REDIS_BACKEND = os.getenv("REDIS_BACKEND", "redis://127.0.0.1:6379/0")
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

CACHE_MIDDLEWARE_ALIAS = 'default'
CACHE_MIDDLEWARE_SECONDS = 300
