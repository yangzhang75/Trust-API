# Trust API container image (Week 1).
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install .

# Migrations are applied at startup by the compose command.
COPY alembic.ini ./
COPY migrations ./migrations

EXPOSE 8000

# Default command; compose overrides to run migrations first.
CMD ["uvicorn", "trust_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
