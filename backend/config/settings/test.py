from .base import *

SECRET_KEY = 'django-insecure-dummy-key-for-testing'
TESTING = True

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db_test.sqlite3',
    }
}
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
    "anon": "1000/minute",
    "user": "1000/minute",
    "login_attempts": "1000/minute",
    "dj_rest_auth": "1000/minute",
}

CELERY_TASK_ALWAYS_EAGER = True
