"""
Django settings for backend_laguna project.
"""

import os
import shutil
import logging.handlers
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file explicitly
ENV_FILE = BASE_DIR / '.env'
if not ENV_FILE.exists():
    ENV_FILE = BASE_DIR.parent / '.env'
if ENV_FILE.exists():
    from dotenv import load_dotenv
    load_dotenv(str(ENV_FILE))

# Determine Environment
ENVIRONMENT = os.getenv('ENVIRONMENT', 'development').strip().lower()
IS_PRODUCTION = ENVIRONMENT == 'production'

# URLs
PRODUCTION_URL = os.getenv('PRODUCTION_URL')
SERVER_URL = os.getenv('SERVER_URL')

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-qkfz4kr257o+r7^5d$+vvr4zbvr@7+_1mq8^y0qzql0c&h*eg0')

# Debug
DEBUG = not IS_PRODUCTION

# Allowed Hosts
if IS_PRODUCTION:
    allowed_hosts_env = os.getenv("ALLOWED_HOSTS", "")
    ALLOWED_HOSTS = allowed_hosts_env.split(",") if allowed_hosts_env else ['127.0.0.1']
else:
    ALLOWED_HOSTS = ['127.0.0.1', 'localhost', '*']

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_extensions',
    'corsheaders',
    'apps.accounts',
    'rest_framework',
    'rest_framework.authtoken',
    'drf_spectacular',
    'apps.data_engine',
    'apps.absenteeism',
    'apps.manning_sheet',
]

MIDDLEWARE = [
    'django.middleware.gzip.GZipMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'backend_laguna.custom_middleware.RequestFilterMiddleware',
]

# CORS settings
if IS_PRODUCTION:
    CORS_ALLOWED_ORIGINS = [
        "https://yuktiai.laguna-clothing.com",
        "https://ascendumai.azurewebsites.net",
    ]
else:
    CORS_ALLOW_ALL_ORIGINS = True
    CORS_ALLOWED_ORIGINS = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://laguna.eastus.cloudapp.azure.com:8000",
        "http://lagunadev-dpg8epc6d7e0h2h7.centralindia-01.azurewebsites.net",
        "http://lagunaai.azurewebsites.net",
        "https://yuktiai.laguna-clothing.com",
        "http://ascpocs.eastus.cloudapp.azure.com:5173",
        "http://ascendumai.azurewebsites.net",
        "https://ascendumai.azurewebsites.net"
    ]

CORS_ALLOW_METHODS = [
    "GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS",
]

CORS_ALLOW_HEADERS = [
    "content-type", "authorization", "x-requested-with", "accept", "origin",
]

CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS

ROOT_URLCONF = 'backend_laguna.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'backend_laguna.wsgi.application'

# Database
if IS_PRODUCTION:
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
else:
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
                'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
            }
        }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'apps.accounts.authentication.MultiSessionTokenAuthentication',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

AUTH_USER_MODEL = 'accounts.User'

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_L10N = True
USE_TZ = True

# Static files and Media
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'static_files')
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Security settings
if IS_PRODUCTION:
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

if IS_PRODUCTION:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = "smtp.sendgrid.net"
    EMAIL_PORT = 587
    EMAIL_USE_TLS = True
    EMAIL_USE_SSL = False
    EMAIL_HOST_USER = "apikey"
    EMAIL_HOST_PASSWORD = SENDGRID_API_KEY
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Logging
LOGGING_DIR = os.path.join(BASE_DIR, "logs")
if not os.path.exists(LOGGING_DIR):
    os.makedirs(LOGGING_DIR)

INFO_LOG_FILE_SUFFIX = 'info.log'
ERROR_LOG_FILE_SUFFIX = 'error.log'
INFO_MIDDLEWARE_LOG_FILE_SUFFIX = 'info_middleware.log'
ERROR_MIDDLEWARE_LOG_FILE_SUFFIX = 'error_middleware.log'

LOG_LEVEL = 'INFO' if IS_PRODUCTION else 'DEBUG'

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
            'filename': os.path.join(LOGGING_DIR, INFO_LOG_FILE_SUFFIX),
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
            'filename': os.path.join(LOGGING_DIR, ERROR_LOG_FILE_SUFFIX),
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
            'filename': os.path.join(LOGGING_DIR, INFO_MIDDLEWARE_LOG_FILE_SUFFIX),
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
            'filename': os.path.join(LOGGING_DIR, ERROR_MIDDLEWARE_LOG_FILE_SUFFIX),
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
            'level': LOG_LEVEL,
            'propagate': False,
        },
        'middleware': {
            'handlers': ['info_middleware', 'error_middleware', 'console'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        '': {
            'handlers': ['console', 'info_file', 'error_file'],
            'level': LOG_LEVEL,
        },
    },
}

# Redis & Celery
REDIS_BACKEND = os.getenv("REDIS_BACKEND", "redis://127.0.0.1:6379/0" if not IS_PRODUCTION else "redis://redis:6379/0")
CELERY_BROKER_URL = REDIS_BACKEND

if IS_PRODUCTION:
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

# Spectacular Settings for OpenAPI / Swagger
SPECTACULAR_SETTINGS = {
    'TITLE': 'Laguna-AI Line Balancing API',
    'DESCRIPTION': 'Interactive API documentation for the Laguna-AI Line Balancing backend application.',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'SECURITY': [{'TokenAuth': []}],
    'APPEND_COMPONENTS': {
        'securitySchemes': {
            'TokenAuth': {
                'type': 'apiKey',
                'in': 'header',
                'name': 'Authorization',
                'description': 'Enter your token in the format: Token <your_token>'
            }
        }
    }
}
