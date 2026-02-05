# Deployment Guide

This guide covers deploying the platform to production environments using Docker Compose or Kubernetes.

## Docker Compose (Production)

For single-node production deployments or testing production configurations.

### 1. Configuration

Create a production environment file:

```bash
cp envs/.env.production .env
```

**Critical Settings to Update:**
*   `POSTGRES_PASSWORD`, `REDIS_PASSWORD`: Set strong passwords.
*   `MLFLOW_ARTIFACT_ROOT`: Point to S3 (`s3://...`) or GCS (`gs://...`).
*   `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` (if using S3).
*   `GOOGLE_APPLICATION_CREDENTIALS` (if using GCS).

### 2. Start Services

Use the production override file:

```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### 3. Scaling

You can scale the API workers:

```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --scale model-api=3
```

## Kubernetes (EKS/GKE)

For scalable, distributed production deployments.

### Prerequisites

*   `kubectl` configured.
*   A running Kubernetes cluster (EKS, GKE, or local Kind/Minikube).

### Deployment Steps

1.  **Apply Base Resources**:

    ```bash
    kubectl apply -f k8s/base/
    ```

2.  **Apply Production Overlays**:

    ```bash
    kubectl apply -f k8s/overlays/production/
## Monitoring & Alerts

*   Configure Prometheus to scrape metrics from the API service.
*   Set up Grafana dashboards using the provided templates in `monitoring/grafana/`.
*   Define alerts for high latency (>500ms) or high error rates (>1%).
