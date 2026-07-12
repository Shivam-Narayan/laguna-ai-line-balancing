"""
Root URL config for the accounts app.
All patterns are defined in api/urls.py — this file simply includes them.
"""
from django.urls import path, include

urlpatterns = [
    path('', include('apps.accounts.api.urls')),
]