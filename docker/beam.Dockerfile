# =============================================================================
# Apache Beam Runner Dockerfile
# =============================================================================
FROM python:3.11-slim

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

# Install Apache Beam and cloud SDKs
RUN pip install --no-cache-dir \
    apache-beam[gcp,aws]==2.53.0 \
    google-cloud-pubsub==2.19.0 \
    google-cloud-bigquery==3.14.0 \
    google-cloud-storage==2.13.0 \
    boto3==1.34.0 \
    confluent-kafka==2.3.0 \
    pandas==2.2.0 \
    numpy==1.26.0

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

# Default command
CMD ["python", "-m", "src.feature_engineering.beam.pipelines"]