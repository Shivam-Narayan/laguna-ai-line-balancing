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

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Common runtime base
FROM python:3.11-slim AS base

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    default-mysql-client \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies from builder
COPY --from=builder /root/.local /root/.local

# Set PATH to use user's local Python packages
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app/apps:/app

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/logs /app/media /app/static_files /app/csv_files

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
CMD ["gunicorn", "backend_laguna.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4"]
