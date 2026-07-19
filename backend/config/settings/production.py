"""
Production settings for backend_laguna.
"""

from .base import *
import os

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    raise ValueError("SECRET_KEY environment variable is required in production!")

DEBUG = False

allowed_hosts_env = os.getenv("ALLOWED_HOSTS", "")
ALLOWED_HOSTS = allowed_hosts_env.split(",") if allowed_hosts_env else ['127.0.0.1']

CORS_ALLOWED_ORIGINS = [
    "https://yuktiai.laguna-clothing.com",
    "https://ascendumai.azurewebsites.net",
]

# CSRF Trusted Origins
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS + [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

# Database
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

# AWS S3 Configuration
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_STORAGE_BUCKET_NAME = os.getenv('AWS_STORAGE_BUCKET_NAME')
AWS_S3_REGION_NAME = os.getenv('AWS_S3_REGION_NAME')
AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com' if AWS_STORAGE_BUCKET_NAME else None
AWS_S3_FILE_OVERWRITE = False
AWS_DEFAULT_ACL = 'private'

if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and AWS_STORAGE_BUCKET_NAME:
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
            "OPTIONS": {
                "location": "media",
                "default_acl": "private",
            },
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
    MEDIA_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/media/'

# Security settings
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_SECURITY_POLICY = {
    'default-src': ("'self'",),
    'script-src': ("'self'", "'unsafe-inline'"),
}

# Email Settings
SENDGRID_API_KEY = os.getenv('SENDGRID_API_KEY')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL')
MAILGUN_API_KEY = os.getenv('MAILGUN_API_KEY')
MAILGUN_DOMAIN = os.getenv('MAILGUN_DOMAIN')
MAILGUN_FROM_EMAIL = os.getenv('MAILGUN_FROM_EMAIL')

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.sendgrid.net"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_USE_SSL = False
EMAIL_HOST_USER = "apikey"
EMAIL_HOST_PASSWORD = SENDGRID_API_KEY

# Logging overrides (INFO level)
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
            'level': 'INFO',
            'propagate': False,
        },
        'middleware': {
            'handlers': ['info_middleware', 'error_middleware', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        '': {
            'handlers': ['console', 'info_file', 'error_file'],
            'level': 'INFO',
        },
    },
}

# Redis & Celery
REDIS_BACKEND = os.getenv("REDIS_BACKEND", "redis://redis:6379/0")
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
