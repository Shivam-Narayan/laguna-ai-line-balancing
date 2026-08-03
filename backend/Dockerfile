# Unified multi-stage Dockerfile for dev + prod
FROM python:3.11-slim AS builder

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    pkg-config \
    default-libmysqlclient-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/

# Create a virtual environment
ENV VIRTUAL_ENV=/opt/venv
RUN uv venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN uv pip install -r requirements.txt

# Common runtime base
FROM python:3.11-slim AS base

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    default-mysql-client \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Set PATH to use the virtual environment
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app/apps:/app

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/media /app/static_files /app/csv_files

# Collect static files (optional, for production)
# RUN python manage.py collectstatic --noinput

# Expose port
EXPOSE 8000

# Shared health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/admin/', timeout=5)" || exit 1

# Development image target
FROM base AS dev
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# Production image target
FROM base AS prod
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4"]
