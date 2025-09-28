# Deployment Guide

## Overview
This repository supports both local development and production deployments with separate Docker Compose configurations.

## Docker Compose Structure

```
docker-compose.yml          # Base services (shared)
docker-compose.local.yml    # Local/demo overrides (MinIO, Redpanda)
docker-compose.prod.yml     # Production overrides (Kafka, cloud storage)
.env.example                # Base environment template
envs/                       # Environment-specific templates
  ├── .env.local           # Local development configuration
  ├── .env.staging         # Staging environment configuration
  └── .env.production      # Production environment configuration
```

## Local Development

### Quick Start
```bash
# Start local environment
./scripts/start-local.sh

# Or manually:
cp envs/.env.local .env
docker-compose -f docker-compose.yml -f docker-compose.local.yml up -d

# Run demo
./scripts/demo/demo.sh

# Stop services
docker-compose -f docker-compose.yml -f docker-compose.local.yml down
```

### Local Services
- **Redpanda**: Lightweight Kafka alternative (port 9092)
- **MinIO**: Local S3-compatible storage (port 9000/9001)
- **MLflow**: With PostgreSQL backend and MinIO artifacts
- **Redis**: Feature store with 256MB memory
- **Model API**: Auto-reload enabled, 2 workers
- **Monitoring**: Prometheus + Grafana

### Local URLs
- Model API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- MLflow: http://localhost:5000
- Grafana: http://localhost:3001 (admin/admin123)
- MinIO: http://localhost:9001 (minioadmin/minioadmin123)
- Prometheus: http://localhost:9090

## Production Deployment

### Prerequisites
1. Cloud storage bucket (S3/GCS) for MLflow artifacts
2. Production database credentials
3. SSL certificates (if using NGINX)
4. Monitoring integration (Sentry/Datadog optional)

### Setup
```bash
# 1. Create production environment file
cp envs/.env.production .env

# 2. Edit .env with production values
vim .env
# Set all CHANGE_ME values:
# - Database passwords
# - Redis password
# - Cloud storage paths
# - API keys

# 3. Start production services
./scripts/start-prod.sh

# Or manually:
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# 4. Enable NGINX (optional)
docker-compose -f docker-compose.yml -f docker-compose.prod.yml --profile web up -d
```

### Production Services
- **Kafka + Zookeeper**: Full Kafka for production messaging
- **PostgreSQL**: Production database with strong passwords
- **Redis**: 1GB memory with password protection
- **MLflow**: Connected to cloud storage (S3/GCS)
- **Model API**: 4 workers, 2 replicas, auto-scaling
- **Monitoring**: Production-grade Prometheus + Grafana

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
      cpus: '1'
      memory: 1.5G
```

#### Security
- All passwords from environment variables
- Redis password protection
- NGINX SSL termination (optional)
- API key authentication
- CORS restrictions

## Environment Variables

### Critical Production Variables
```bash
# Database
POSTGRES_PASSWORD=strong_password_here
POSTGRES_USER=mlflow_prod
POSTGRES_DB=mlflow_production

# Redis
REDIS_PASSWORD=redis_password_here

# Cloud Storage (choose one)
# AWS
MLFLOW_ARTIFACT_ROOT=s3://your-bucket/mlflow
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret

# GCP
MLFLOW_ARTIFACT_ROOT=gs://your-bucket/mlflow
GCP_PROJECT=your-project
GOOGLE_APPLICATION_CREDENTIALS=/app/gcp-key.json

# API
PRELOAD_MODELS=model_name:production
API_WORKERS=4
MODEL_CACHE_SIZE=10

# Monitoring
GRAFANA_ADMIN_PASSWORD=secure_password
```

## Deployment Commands

### Local
```bash
# Start
docker-compose -f docker-compose.yml -f docker-compose.local.yml up -d

# Logs
docker-compose -f docker-compose.yml -f docker-compose.local.yml logs -f model-api

# Stop
docker-compose -f docker-compose.yml -f docker-compose.local.yml down

# Clean everything
docker-compose -f docker-compose.yml -f docker-compose.local.yml down -v
```

### Production
```bash
# Start
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Scale API
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --scale model-api=3

# Update single service
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-deps model-api

# Logs
docker-compose -f docker-compose.yml -f docker-compose.prod.yml logs -f

# Stop
docker-compose -f docker-compose.yml -f docker-compose.prod.yml down
```

## Health Checks

All services include health checks:

```bash
# Check all services
for service in 8000 5000 9090 3001; do
  echo "Checking port $service..."
  curl -s http://localhost:$service/health || echo "Not ready"
done

# Production health endpoint
curl https://your-domain.com/health
```

## Monitoring

### Metrics Available
- API request latency
- Model prediction time
- Cache hit rates
- Model version tracking
- Resource utilization

### Grafana Dashboards
1. API Performance
2. Model Metrics
3. Infrastructure Health
4. Cache Performance

## Troubleshooting

### Local Issues
```bash
# Reset everything
docker-compose -f docker-compose.yml -f docker-compose.local.yml down -v
rm -rf model_cache/
docker-compose -f docker-compose.yml -f docker-compose.local.yml up -d

# Check MinIO bucket
docker exec ml-mlflow-minio mc ls local/mlflow
```

### Production Issues
```bash
# Check service status
docker-compose -f docker-compose.yml -f docker-compose.prod.yml ps

# View recent logs
docker-compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=100

# Restart single service
docker-compose -f docker-compose.yml -f docker-compose.prod.yml restart model-api
```

## Migration Guide

### From Local to Production
1. Train models in local environment
2. Promote models to "Production" stage in MLflow
3. Export model artifacts to cloud storage
4. Update production `.env` with model names
5. Deploy production services
6. Verify model loading

### Rollback Procedure
1. Change model stage in MLflow UI
2. API auto-updates within 60 seconds
3. Or force reload: `curl -X POST https://api/models/reload`

## Best Practices

1. **Never commit `.env` files** with real credentials
2. **Use separate MLflow experiments** for dev/staging/prod
3. **Monitor resource usage** and adjust limits
4. **Regular backups** of PostgreSQL and model artifacts
5. **Use health checks** before routing traffic
6. **Implement gradual rollouts** with multiple API replicas
7. **Set up alerts** in Grafana for critical metrics