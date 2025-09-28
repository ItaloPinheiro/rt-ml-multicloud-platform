# =============================================================================
# MLflow Tracking Server Dockerfile
# =============================================================================
FROM python:3.11-slim

LABEL maintainer="Italo Pinheiro <italo@example.com>"
LABEL description="MLflow tracking server with S3 and PostgreSQL support"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Install Poetry
RUN pip install poetry==1.7.1

# Copy dependency files
COPY pyproject.toml poetry.lock ./

# Configure Poetry and install dependencies
# MLflow and its dependencies should be in pyproject.toml
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --only main

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