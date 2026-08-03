"""
Root conftest.py for pytest.

Ensures the backend directory is on sys.path and Django is fully
initialized before test collection begins. This is needed because
VS Code runs pytest from the workspace root (c:\\Projects\\laguna),
not from the backend/ directory.
"""
import sys
import os
from pathlib import Path

# Add this directory (backend/) to the front of sys.path
# so that 'config.settings', 'apps.*', etc. are importable.
backend_dir = str(Path(__file__).resolve().parent)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402
django.setup()
