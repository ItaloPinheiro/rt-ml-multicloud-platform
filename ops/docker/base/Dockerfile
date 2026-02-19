# =============================================================================
# ML Pipeline Platform - Main Application Dockerfile
# =============================================================================
FROM python:3.13-slim

LABEL maintainer="ML Pipeline Platform Team"
LABEL description="Main ML Pipeline Platform application container"
LABEL version="1.0.0"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Install Poetry for dependency management
ENV POETRY_HOME="/opt/poetry"
ENV POETRY_CACHE_DIR="/opt/poetry/cache"
ENV POETRY_VENV_IN_PROJECT=1
ENV POETRY_NO_interaction=1

RUN pip install --no-cache-dir poetry==1.7.1

# Copy dependency files
COPY pyproject.toml poetry.lock ./

# Configure Poetry and install dependencies
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --only main

# Copy application source code
COPY src ./src
COPY configs ./configs
COPY scripts ./scripts

# Set Python environment variables
ENV PYTHONPATH=/app:$PYTHONPATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Create non-root user for security
RUN groupadd -r mlpipeline && useradd -r -g mlpipeline mlpipeline
RUN chown -R mlpipeline:mlpipeline /app
USER mlpipeline

# Create directories for data and logs
RUN mkdir -p /app/data /app/logs

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose application port
EXPOSE 8000

# Default command (can be overridden)
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]