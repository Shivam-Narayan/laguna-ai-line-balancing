"""
ASGI config for backend_laguna project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/asgi/

What is ASGI?

ASGI (Asynchronous Server Gateway Interface) is the modern successor to WSGI that supports both synchronous and asynchronous programming.

It can handle:
- Async requests
- WebSockets
- Background tasks
- High concurrency

Architecture Flow:
Client
   ↓
Nginx
   ↓
Uvicorn/Daphne
   ↓
Django/FastAPI
   ↓
Response

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

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()
