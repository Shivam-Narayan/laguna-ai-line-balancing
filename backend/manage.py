#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    # For development, use dev settings directly
    # For production, use the router (which checks ENVIRONMENT)
    environment = os.getenv('ENVIRONMENT', 'development').strip().lower()
    
    if environment == 'development':
        settings_module = 'backend_laguna.settings.dev'
    else:
        settings_module = 'backend_laguna.settings.prod'
    
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', settings_module)
    
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    execute_from_command_line(sys.argv)

if __name__ == '__main__':
    main()
