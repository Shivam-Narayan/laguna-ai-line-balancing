"""
Settings initialization.
This dynamically loads either development.py or production.py based on the ENVIRONMENT variable.
"""

import os
from pathlib import Path

# Load .env file explicitly to get the ENVIRONMENT variable early on
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / '.env'
if not ENV_FILE.exists():
    ENV_FILE = BASE_DIR.parent / '.env'
    
if ENV_FILE.exists():
    from dotenv import load_dotenv
    load_dotenv(str(ENV_FILE))

ENVIRONMENT = os.getenv('ENVIRONMENT', 'development').strip().lower()

if ENVIRONMENT == 'production':
    from .production import *
else:
    from .development import *
