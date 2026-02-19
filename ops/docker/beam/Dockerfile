# =============================================================================
# Apache Beam Runner Dockerfile
# =============================================================================
FROM python:3.13-slim

LABEL maintainer="Italo Pinheiro <italo@example.com>"
LABEL description="Apache Beam pipeline runner with multi-cloud support"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    git \
    default-jre \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Install Poetry
RUN pip install poetry==1.7.1

# Copy dependency files
COPY pyproject.toml poetry.lock ./

# Configure Poetry and install dependencies
# Apache Beam and its dependencies should be in pyproject.toml
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --only main

# Copy application code
COPY src ./src
COPY configs ./configs

# Set environment variables
ENV PYTHONPATH=/app:$PYTHONPATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Create non-root user
RUN groupadd -r beam && useradd -r -g beam beam
RUN chown -R beam:beam /app
USER beam

# Default command - just sleep to keep container running
CMD ["sleep", "infinity"]