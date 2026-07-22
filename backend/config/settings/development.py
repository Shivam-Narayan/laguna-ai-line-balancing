"""
Development settings for backend_laguna.
"""

from .base import *

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-qkfz4kr257o+r7^5d$+vvr4zbvr@7+_1mq8^y0qzql0c&h*eg0')

DEBUG = True

ALLOWED_HOSTS = ['127.0.0.1', 'localhost']

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://laguna.eastus.cloudapp.azure.com:8000",
    "http://lagunadev-dpg8epc6d7e0h2h7.centralindia-01.azurewebsites.net",
    "http://lagunaai.azurewebsites.net",
    "https://yuktiai.laguna-clothing.com",
    "http://ascpocs.eastus.cloudapp.azure.com:5173",
    "http://ascendumai.azurewebsites.net",
    "https://ascendumai.azurewebsites.net"
]
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^http://localhost:\d+$",
    r"^http://127\.0\.0\.1:\d+$",
]

# CSRF Trusted Origins
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS + [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

# Database
if os.getenv('DB_ENGINE'):
    DATABASES = {
        'default': {
            'ENGINE': os.getenv('DB_ENGINE', 'django.db.backends.postgresql'),
            'NAME': os.getenv('DB_NAME', 'Laguna'),
            'USER': os.getenv('DB_USER', 'postgres'),
            'PASSWORD': os.getenv('DB_PASSWORD', 'root'),
            'HOST': os.getenv('DB_HOST', '127.0.0.1'),
            'PORT': os.getenv('DB_PORT', '5432'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Email Backend
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Logging overrides (DEBUG level)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'detailed': {
            'format': '%(asctime)s - %(levelname)s - %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S'
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'detailed',
        },
        'info_file': {
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': LOGGING_DIR / INFO_LOG_FILE_SUFFIX,
            'level': 'INFO',
            'when': 'D',
            'interval': 1,
            'backupCount': 7,
            'formatter': 'detailed',
            'encoding': 'utf-8',
            'delay': True,
        },
        'error_file': {
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': LOGGING_DIR / ERROR_LOG_FILE_SUFFIX,
            'level': 'ERROR',
            'when': 'D',
            'interval': 1,
            'backupCount': 7,
            'formatter': 'detailed',
            'encoding': 'utf-8',
            'delay': True,
        },
        'info_middleware': {
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': LOGGING_DIR / INFO_MIDDLEWARE_LOG_FILE_SUFFIX,
            'level': 'INFO',
            'when': 'D',
            'interval': 1,
            'backupCount': 7,
            'formatter': 'detailed',
            'encoding': 'utf-8',
            'delay': True,
        },
        'error_middleware': {
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': LOGGING_DIR / ERROR_MIDDLEWARE_LOG_FILE_SUFFIX,
            'level': 'ERROR',
            'when': 'D',
            'interval': 1,
            'backupCount': 7,
            'formatter': 'detailed',
            'encoding': 'utf-8',
            'delay': True,
        },
    },
    'loggers': {
        'general': {
            'handlers': ['info_file', 'error_file', 'console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'middleware': {
            'handlers': ['info_middleware', 'error_middleware', 'console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        '': {
            'handlers': ['console', 'info_file', 'error_file'],
            'level': 'DEBUG',
        },
    },
}

# Redis & Celery
REDIS_BACKEND = os.getenv("REDIS_BACKEND", "redis://127.0.0.1:6379/0")
CELERY_BROKER_URL = REDIS_BACKEND

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
