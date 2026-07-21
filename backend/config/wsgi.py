"""
WSGI config for backend_laguna project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()

"""
WSGI (Web Server Gateway Interface) is a specification that allows web servers to communicate with Python web applications. It handles synchronous (one request at a time) processing.

Problem with WSGI
Suppose a request takes 10 seconds.

Request 1
   ↓
Processing (10 sec)
   ↓
Completed
   ↓
Request 2 starts

WSGI is not ideal for:
- WebSockets
- Real-time applications
- High concurrency
- Long-running API calls

Comparison:
| WSGI                                     | ASGI                                  |
| ---------------------------------------- | ------------------------------------- |
| Synchronous                              | Asynchronous + Synchronous            |
| One request at a time                    | Handles multiple requests efficiently |
| No WebSockets support                    | Supports WebSockets                   |
| Gunicorn                                 | Uvicorn, Daphne                       |
| Traditional Django                       | Modern Django & FastAPI               |
| Less suitable for real-time applications | Suitable for real-time applications   |
"""
