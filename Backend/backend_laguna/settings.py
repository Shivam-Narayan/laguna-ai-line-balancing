"""
Django settings router for backend_laguna project.

This module routes to environment-specific settings (dev, prod).
"""

import os
from pathlib import Path

# Get the Backend directory (where .env is located)
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / '.env'

# Load .env file explicitly
if ENV_FILE.exists():
    from dotenv import load_dotenv
    load_dotenv(str(ENV_FILE))

# Determine which settings module to use based on ENVIRONMENT
ENVIRONMENT = os.getenv('ENVIRONMENT', 'development').strip().lower()

if ENVIRONMENT == 'development':
    from .settings.dev import *  # noqa
else:
    from .settings.prod import *  # noqa
