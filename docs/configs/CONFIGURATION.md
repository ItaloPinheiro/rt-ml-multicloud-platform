# Configuration Guide

This document provides comprehensive guidance for configuring the ML Pipeline Platform across different environments.

## Quick Start

1. **Copy environment file**: `cp .env.example .env`
2. **Update environment variables** in `.env` with your credentials
3. **Choose configuration**: Use appropriate YAML config for your environment
4. **Run setup**: `./scripts/setup/install.sh`

## Configuration Files

The platform uses YAML configuration files in the `configs/` directory:

### Available Configurations

- **`configs/development.yaml`** - Local development environment
- **`configs/staging.yaml`** - Staging environment with production-like settings
- **`configs/production.yaml`** - Production environment with full security

### Configuration Structure

Each configuration file contains the following sections:

#### Database Settings
```yaml
database:
  host: ${DATABASE_HOST}
  port: ${DATABASE_PORT:-5432}
  database: ${DATABASE_NAME}
  username: ${DATABASE_USER}
  password: ${DATABASE_PASSWORD}
  ssl_mode: require
```

#### Redis (Feature Store)
```yaml
redis:
  host: ${REDIS_HOST}
  port: ${REDIS_PORT:-6379}
  password: ${REDIS_PASSWORD}
  max_connections: 100
```

#### MLflow Model Management
```yaml
mlflow:
  tracking_uri: ${MLFLOW_TRACKING_URI}
  registry_uri: ${MLFLOW_REGISTRY_URI}
  experiment_name: ${MLFLOW_EXPERIMENT_NAME}
  artifact_location: ${MLFLOW_ARTIFACT_ROOT}
```

#### Stream Processing
```yaml
# Google Cloud Pub/Sub
pubsub:
  project_id: ${GCP_PROJECT}
  credentials_path: ${GOOGLE_APPLICATION_CREDENTIALS}

# AWS Kinesis
kinesis:
  region: ${AWS_REGION}
  access_key_id: ${AWS_ACCESS_KEY_ID}
  secret_access_key: ${AWS_SECRET_ACCESS_KEY}

# Apache Kafka
kafka:
  bootstrap_servers: ${KAFKA_BOOTSTRAP_SERVERS}
  security_protocol: ${KAFKA_SECURITY_PROTOCOL}
  sasl_username: ${KAFKA_SASL_USERNAME}
  sasl_password: ${KAFKA_SASL_PASSWORD}
```

## Environment Variables

### Required Environment Variables

Copy `.env.example` to `.env` and update the following:

#### Cloud Provider Credentials

**Google Cloud Platform:**
```bash
GCP_PROJECT=your-gcp-project-id
GCP_REGION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

**Amazon Web Services:**
```bash
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
```

#### Database Configuration
```bash
# PostgreSQL for MLflow backend
POSTGRES_USER=mlflow
POSTGRES_PASSWORD=mlflow123
POSTGRES_DB=mlflow
POSTGRES_HOST=localhost
POSTGRES_PORT=5433
```

#### MLflow Configuration
```bash
MLFLOW_TRACKING_URI=http://localhost:5000
MLFLOW_BACKEND_STORE_URI=postgresql://mlflow:mlflow123@localhost:5433/mlflow
MLFLOW_ARTIFACT_ROOT=s3://mlflow
MLFLOW_S3_ENDPOINT_URL=http://localhost:9000
```

#### Redis Configuration
```bash
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=""
```

#### Stream Processing
```bash
# Kafka
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_TOPIC=ml-pipeline-events
KAFKA_GROUP_ID=ml-pipeline-consumer

# Pub/Sub
PUBSUB_SUBSCRIPTION=ml-pipeline-subscription
PUBSUB_TOPIC=ml-pipeline-topic

# Kinesis
KINESIS_STREAM_NAME=ml-pipeline-stream
```

#### API and Monitoring
```bash
API_HOST=0.0.0.0
API_PORT=8000
LOG_LEVEL=INFO
PROMETHEUS_PORT=9090
GRAFANA_PORT=3001
GRAFANA_ADMIN_PASSWORD=admin123
```

#### Security
```bash
SECRET_KEY=your-super-secret-key-change-in-production
API_CORS_ORIGINS=["http://localhost:3000", "http://localhost:8080"]
```

### Environment-Specific Variables

#### Development Environment
- Uses local services (localhost)
- Debug mode enabled
- Relaxed security settings
- Mock services available

#### Staging Environment
- Production-like configuration
- Reduced resource allocation
- Debug endpoints enabled for testing
- SSL/TLS required

#### Production Environment
- Full security enabled
- High resource allocation
- No debug endpoints
- Comprehensive monitoring

## Configuration Loading

The application loads configuration in this order:

1. **Environment variables** from `.env` file
2. **YAML configuration** from `configs/{environment}.yaml`
3. **Default values** as specified in config files

Environment variables always take precedence over YAML values.

## Security Best Practices

### Sensitive Data
- Never commit `.env` files to version control
- Use environment variables for all passwords and API keys
- Rotate credentials regularly
- Use different credentials for each environment

### SSL/TLS Configuration
- **Development**: SSL disabled for local services
- **Staging/Production**: SSL required for all external connections
- Configure proper certificate validation

### Access Control
- Use service accounts with minimal required permissions
- Enable authentication for all production services
- Configure firewall rules appropriately

## Troubleshooting

### Common Issues

**Configuration not loading:**
- Verify `.env` file exists and has correct syntax
- Check YAML syntax in configuration files
- Ensure environment variables are properly set

**Database connection errors:**
- Verify database credentials in `.env`
- Check if database service is running
- Validate network connectivity

**Stream processing issues:**
- Confirm cloud provider credentials
- Verify service account permissions
- Check network policies and firewall rules

### Validation

To validate your configuration:

```bash
# Check environment variables
./scripts/setup/install.sh

# Test database connection
docker-compose up -d postgres-mlflow
docker-compose logs postgres-mlflow

# Verify MLflow setup
docker-compose up -d mlflow-server
curl http://localhost:5000/health
```

## Migration Between Environments

When moving between environments:

1. **Update `.env`** with environment-specific credentials
2. **Choose appropriate config**: Use corresponding YAML file
3. **Update infrastructure**: Deploy environment-specific resources
4. **Validate services**: Run health checks on all components
5. **Test connectivity**: Verify integration between services

For assistance with configuration, see the main README.md or run:
```bash
./scripts/setup/install.sh --help
```