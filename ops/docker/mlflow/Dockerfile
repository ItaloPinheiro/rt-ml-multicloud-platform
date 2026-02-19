# =============================================================================
# MLflow Tracking Server Dockerfile
# =============================================================================
# Stage 1: Builder
FROM python:3.13-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    git \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install poetry==1.7.1

# Copy dependency files
COPY pyproject.toml poetry.lock README.md ./

# Configure Poetry to create venv in project
ENV POETRY_NO_INTERACTION=1

# Install dependencies (only main)
RUN poetry config virtualenvs.in-project true \
    && poetry install --no-interaction --no-ansi --only main --no-root

# Stage 2: Runtime
FROM python:3.13-slim AS runtime

LABEL maintainer="Italo Pinheiro <italo@example.com>"
LABEL description="MLflow tracking server with S3 and PostgreSQL support"

WORKDIR /app

# Install minimal runtime dependencies
RUN apt-get update && apt-get install -y \
    curl \
    postgresql-client \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app:$PYTHONPATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Create non-root user
RUN groupadd -r mlflow && useradd -r -g mlflow mlflow
RUN chown -R mlflow:mlflow /app
USER mlflow

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Expose port
EXPOSE 5000

# Default command (can be overridden)
CMD ["mlflow", "server", "--host", "0.0.0.0", "--port", "5000"]