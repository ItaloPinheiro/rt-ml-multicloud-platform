# Deployment Guide

## Overview

The platform supports local development and production deployments with different Docker Compose configurations.

## Configuration Files

```
docker-compose.yml          # Base services
docker-compose.local.yml    # Local overrides (MinIO, Redpanda)
docker-compose.prod.yml     # Production overrides (Kafka, scaling)
.env.example                # Environment template
```

## Local Development

### Quick Start

```bash
# Setup environment
cp .env.example .env

# Start services
docker-compose up -d

# Run demo
./scripts/demo/demo.sh

# Stop services
docker-compose down
```

### Local Services
- **Redpanda**: Lightweight Kafka (port 9092)
- **MinIO**: S3-compatible storage (ports 9000/9001)
- **MLflow**: Model registry with PostgreSQL
- **Redis**: Feature caching
- **Model API**: FastAPI with hot reload
- **Monitoring**: Prometheus + Grafana

## Production Deployment

### Prerequisites
- Cloud storage for MLflow artifacts (S3/GCS)
- Production database credentials
- Sufficient resources (4+ CPU cores, 8+ GB RAM)

### Setup

```bash
# 1. Create production environment
cp envs/.env.production .env

# 2. Edit .env with production values:
# - Strong passwords for PostgreSQL and Redis
# - Cloud storage configuration (S3/GCS)
# - API authentication keys

# 3. Start production services
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# 4. Verify deployment
curl http://localhost:8000/health
```

### Production Configuration

#### Resource Limits
```yaml
model-api:
  deploy:
    replicas: 2
    resources:
      limits:
        cpus: '2'
        memory: 4G

redis:
  resources:
    limits:
      memory: 1.5G
```

#### Security
- Password protection for all services
- Environment variable isolation
- API key authentication
- CORS restrictions

## Environment Variables

### Required for Production

```bash
# Database
POSTGRES_PASSWORD=<strong_password>
POSTGRES_USER=mlflow_prod
POSTGRES_DB=mlflow_production

# Redis
REDIS_PASSWORD=<redis_password>

# Cloud Storage (choose one)
# AWS S3
MLFLOW_ARTIFACT_ROOT=s3://your-bucket/mlflow
AWS_ACCESS_KEY_ID=<your_key>
AWS_SECRET_ACCESS_KEY=<your_secret>

# Google Cloud Storage
MLFLOW_ARTIFACT_ROOT=gs://your-bucket/mlflow
GCP_PROJECT=<your-project>
GOOGLE_APPLICATION_CREDENTIALS=/app/gcp-key.json

# API Configuration
API_WORKERS=4
MODEL_CACHE_SIZE=10
MODEL_UPDATE_INTERVAL=60
```

## Kubernetes Deployment

Deploy to Kubernetes cluster:

```bash
# Apply base configuration
kubectl apply -f k8s/base/

# Apply production overlay
kubectl apply -f k8s/overlays/production/

# Check deployment
kubectl get pods -l app=ml-pipeline

# View logs
kubectl logs -l app=ml-pipeline-api -f
```

## Health Checks

All services include health endpoints:

```bash
# Check individual services
curl http://localhost:8000/health  # API
curl http://localhost:5000/health  # MLflow
curl http://localhost:9090/-/healthy  # Prometheus
curl http://localhost:3001/api/health  # Grafana
```

## Scaling

### Docker Compose
```bash
# Scale API replicas
docker-compose -f docker-compose.yml -f docker-compose.prod.yml \
  up -d --scale model-api=3
```

### Kubernetes
```bash
# Scale deployment
kubectl scale deployment ml-pipeline-api --replicas=5
```

## Monitoring

### Available Metrics
- Request latency (P50, P95, P99)
- Prediction throughput
- Model version tracking
- Cache hit rates
- Resource utilization

### Grafana Access
- URL: http://localhost:3001
- Default: admin/admin123
- Change password in production

## Backup and Recovery

### Database Backup
```bash
# Backup MLflow database
docker exec postgres pg_dump -U mlflow mlflow_production > backup.sql

# Restore database
docker exec -i postgres psql -U mlflow mlflow_production < backup.sql
```

### Model Artifacts
Models are stored in cloud storage (S3/GCS) which should have its own backup strategy.

## Troubleshooting

### Service Issues
```bash
# Check status
docker-compose ps

# View logs
docker-compose logs --tail=100 model-api

# Restart service
docker-compose restart model-api
```

### Performance Issues
```bash
# Monitor resources
docker stats

# Check metrics
curl http://localhost:8000/metrics
```

## Migration from Local to Production

1. Export models from local MLflow
2. Upload to production artifact storage
3. Update production database with model metadata
4. Deploy production services
5. Verify model loading

## Best Practices

1. Use separate MLflow experiments for environments
2. Implement gradual rollouts for new models
3. Monitor resource usage and scale accordingly
4. Regular database backups
5. Use health checks before routing traffic
6. Keep audit logs of model deployments