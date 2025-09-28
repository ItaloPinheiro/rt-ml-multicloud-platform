# ML Pipeline Platform Demo Guide

## Overview
This comprehensive demo showcases the complete ML pipeline workflow including model training, versioning, storage, automatic updates, and serving.

## Data Structure

The demo uses a well-organized data structure for clarity and maintainability:

```
sample_data/
├── demo/                   # Demo-specific curated data
│   ├── config.env         # Demo configuration
│   ├── datasets/          # Training datasets
│   │   └── fraud_detection.csv
│   └── requests/          # API test requests
│       ├── baseline.json  # Version 1 model test
│       └── improved.json  # Version 2 model test
├── generated/             # Generated data (gitignored)
│   ├── transactions.json
│   └── user_features.json
└── production/            # Production-like datasets
```

For more details, see [sample_data/README.md](../sample_data/README.md).

## Demo Scripts

### Comprehensive Demo
```bash
./scripts/demo/demo.sh
```
Full demonstration including:
- Model versioning
- MLflow registry management
- MinIO S3 storage verification
- Automatic model updates
- Multi-version predictions

## 🎯 What You'll Learn

- **Model Lifecycle**: Training → Registration → Staging → Production
- **Storage Integration**: Models stored in MinIO S3
- **Automatic Updates**: API auto-detects new Production models
- **Version Management**: Multiple model versions with rollback
- **Real-time Serving**: Low-latency predictions with caching

## Step-by-Step Workflow

### 1. Start Services
```bash
# Start all services
docker-compose -f docker-compose.yml -f docker-compose.local.yml up -d

# Verify services are running
docker-compose ps

# Check health endpoints
curl http://localhost:8000/health  # API
curl http://localhost:5000/health  # MLflow
```

### 2. Generate Sample Data (if needed)
```bash
# Generate sample data
python scripts/demo/generate_data.py

# This creates:
# - sample_data/demo/datasets/fraud_detection.csv (training data)
# - sample_data/demo/requests/*.json (API test requests)
# - sample_data/generated/*.json (raw generated data)
```

### 3. Train Initial Model (Version 1)
```bash
# Using Docker (recommended)
docker exec ml-beam-runner python -m src.models.training.train \
    --data-path /app/sample_data/demo/datasets/fraud_detection.csv \
    --mlflow-uri http://mlflow-server:5000 \
    --experiment fraud_detection \
    --model-name fraud_detector

# Or using local Python
python scripts/demo/utilities/quick_train_model.py
```

### 3. Check Model in MLflow

#### Via Web UI
Navigate to http://localhost:5000
- Click "Models" tab
- View "fraud_detector" model
- See version details and artifacts

#### Via API
```bash
# List all registered models
curl http://localhost:5000/api/2.0/mlflow/registered-models/list | jq

# Get specific model
curl -X POST http://localhost:5000/api/2.0/mlflow/registered-models/search \
    -H "Content-Type: application/json" \
    -d '{"filter": "name=\"fraud_detector\""}' | jq
```

#### Via Python Script
```bash
python scripts/model_scripts/list_models.py
```

### 4. Verify Storage in MinIO

#### Via Web Console
1. Navigate to http://localhost:9001
2. Login: `minioadmin` / `minioadmin123`
3. Browse bucket: `mlflow`
4. View stored model artifacts

#### Via CLI
```bash
# List all objects in MinIO
docker exec ml-mlflow-minio mc ls local/mlflow/ --recursive
```

### 5. Check Current Model in API
```bash
# Get current loaded model
curl http://localhost:8000/models/current | jq

# Response shows:
{
  "name": "fraud_detector",
  "version": "1",
  "stage": "Production",
  "loaded_at": "2024-01-20T10:30:00Z"
}
```

### 6. Make Prediction with Version 1
```bash
# Using baseline request
curl -X POST http://localhost:8000/predict \
    -H "Content-Type: application/json" \
    -d @sample_data/demo/requests/baseline.json | jq
```

### 7. Train New Model Version
```bash
# Train improved model (Version 2) with different parameters
docker exec ml-beam-runner python -m src.models.training.train \
    --data-path /app/sample_data/demo/datasets/fraud_detection.csv \
    --mlflow-uri http://mlflow-server:5000 \
    --experiment fraud_detection \
    --model-name fraud_detector \
    --max-depth 8 \
    --n-estimators 150
```

### 8. Wait for Automatic Update (60 seconds)

The Model API checks for updates every 60 seconds:

```bash
# Watch API logs for update
docker-compose -f docker-compose.yml -f docker-compose.local.yml logs -f model-api

# You'll see:
# [INFO] New model version detected: fraud_detector v2
# [INFO] Loading model version 2 from MLflow
# [INFO] Model loaded successfully
# [INFO] Swapped to model version 2
```

### 9. Verify New Model is Loaded
```bash
# Check current model (should show version 2)
curl http://localhost:8000/models/current | jq
```

### 10. Make Prediction with Version 2
```bash
# Same endpoint, new model version
curl -X POST http://localhost:8000/predict \
    -H "Content-Type: application/json" \
    -d @sample_data/demo/requests/improved.json | jq

# Response includes model version
{
  "prediction": 1,
  "probability": 0.89,
  "model_version": "2",
  "response_time_ms": 15.3
}
```

## 🐳 Docker Services Architecture

The platform runs entirely in Docker containers for consistency and portability:

### Core Services (Always Running)
- **model-api**: FastAPI prediction service (port 8000)
- **mlflow-server**: Model registry and tracking (port 5000)
- **mlflow-db**: PostgreSQL for MLflow metadata (port 5433)
- **mlflow-minio**: S3-compatible object storage (ports 9000, 9001)
- **redis**: Feature caching (port 6379)
- **redpanda**: Kafka-compatible message broker (port 9092)

### Optional Services
- **beam-runner**: Apache Beam pipeline runner (profile: beam)
  - Used for training models in containerized environment
  - Activated with `--profile beam` flag
- **prometheus**: Metrics collection (port 9090)
- **grafana**: Dashboards (port 3001)

### Service Dependencies
```
model-api → mlflow-server → mlflow-db
         ↘                ↗
           mlflow-minio
         ↓
        redis
```

## 📋 Prerequisites

### System Requirements
- **RAM**: 8GB+ recommended
- **Storage**: 10GB+ free space
- **OS**: Linux, macOS, or Windows with WSL2

### Required Software
- Docker & Docker Compose
- Python 3.11+
- Git
- curl or Postman (for API testing)
- pip (Python package installer)

### Optional (for cloud deployment)
- kubectl
- gcloud CLI (for GCP)
- aws CLI + eksctl (for AWS)

## 🐍 Python Dependency Management

This project supports two dependency management approaches: **Poetry** (recommended) and **pip + venv** (alternative). Choose the approach that best fits your workflow.

### Option A: Poetry Setup (Recommended)

Poetry provides deterministic builds and better dependency resolution. This is the recommended approach for this project.

```bash
# Install Poetry (if not already installed)
pip install poetry

# Install dependencies and create virtual environment
poetry install

# Activate Poetry shell
poetry shell

# Verify installation
poetry env info
```

**Benefits of Poetry:**
- Deterministic builds with `poetry.lock`
- Automatic dependency resolution
- Integrated virtual environment management
- Better for team collaboration

### Option B: Manual Virtual Environment Setup (Alternative)

If you prefer traditional pip + venv workflow:

```bash
# Install Poetry temporarily (needed for Docker builds)
pip install poetry

# Generate poetry.lock file for Docker compatibility
poetry lock --no-update

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows (Git Bash/Command Prompt/PowerShell):
source .venv/Scripts/activate

# Linux/macOS:
source .venv/bin/activate

# Upgrade pip and install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### Verify Environment Setup

```bash
# Check if virtual environment is active (should show project path)
which python

# Check installed packages
pip list  # or: poetry show (if using Poetry)

# Verify Poetry can build Docker images (run from project root)
docker-compose build model-api
```

## 🚀 Quick Start Demo (10 minutes)

### 1. Clone and Setup

```bash
# Clone the repository
git clone https://github.com/your-org/rt-ml-multicloud-platform.git
cd rt-ml-multicloud-platform

# Choose your setup approach:

# Option A: Poetry setup
pip install poetry
poetry install
poetry shell

# Option B: pip + venv setup
pip install poetry          # Temporary install for Docker compatibility
poetry lock --no-update     # Generate poetry.lock for Docker builds
./scripts/setup.sh          # Creates .venv and installs dependencies
source .venv/Scripts/activate  # Windows
# source .venv/bin/activate    # Linux/macOS

# Start all services (works with either approach)
docker-compose up -d

# Wait for services to be ready (30-60 seconds)
sleep 30
# Check health endpoint
curl http://localhost:8000/health || echo "API not ready yet"
```

### 2. Load Sample Data

```bash
# Ensure environment is activated
# Poetry users: poetry shell (if not already active)
# pip users: source .venv/Scripts/activate (Windows) or source .venv/bin/activate (Linux/macOS)

# Sample data is now organized in a structured format
ls -la sample_data/demo/
# - config.env: Demo configuration
# - datasets/fraud_detection.csv: Training data
# - requests/: API test requests

# Verify API service is running
curl http://localhost:8000/health

# If you need to generate new sample data:
python scripts/demo/generate_data.py
```

### 3. Train Initial Model

```bash
# Option A: Train using Docker (Recommended)
./scripts/demo/train_docker.sh

# Option B: Train using quick script in container
./scripts/demo/train_in_container.sh

# Option C: Train locally (requires environment activation)
python scripts/demo/quick_train_model.py

# Check MLflow UI to verify model training
open http://localhost:5000

# View registered models
curl http://localhost:5000/api/2.0/mlflow/registered-models/list
```

### 4. Make Predictions

```bash
# First, ensure the model API is running
docker-compose ps model-api

# Single prediction using the baseline request file
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d @sample_data/demo/requests/baseline.json

# Or with inline JSON
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "features": {
      "amount": 1500.00,
      "merchant_category": "jewelry",
      "hour_of_day": 22,
      "is_weekend": false,
      "risk_score": 0.8
    },
    "model_name": "fraud_detector",
    "return_probabilities": true
  }'

# Alternative: Use the simple prediction endpoint
curl -X POST http://localhost:8000/simple-predict \
  -H "Content-Type: application/json" \
  -d '{"features": [1500.00, 0.8, 22, 0, 1, 0, 0, 1, 0.5]}'

# Expected response:
# {
#   "prediction": 1,
#   "probabilities": [0.2, 0.8],
#   "model_name": "fraud_detector",
#   "model_version": "1",
#   "latency_ms": 25.3
# }
```

### 5. View Monitoring Dashboards

```bash
# Prometheus metrics
open http://localhost:9090

# Grafana dashboards (admin/admin)
open http://localhost:3001
```

## 🔧 Detailed Demo Scenarios

> **Note**: For all Python scripts in the following scenarios, ensure your environment is activated:
> ```bash
> # Poetry users:
> poetry shell
>
> # pip + venv users:
> # Windows: source .venv/Scripts/activate
> # Linux/macOS: source .venv/bin/activate
> ```

### Scenario 1: Fraud Detection Pipeline

#### Overview
Simulate a real-time fraud detection system processing credit card transactions.

#### Steps

1. **Start Stream Simulation**
```bash
# Activate virtual environment first
source .venv/Scripts/activate  # Windows
# source .venv/bin/activate    # Linux/macOS

# Generate synthetic transaction stream
python scripts/simulate_transactions.py --rate 100 --duration 300
```

2. **Monitor Feature Store**
```bash
# Check feature store metrics
curl http://localhost:8000/metrics | grep feature_store

# View stored features (ensure .venv is activated)
python scripts/inspect_features.py --entity-id user_123
```

3. **Analyze Predictions**
```bash
# Get prediction statistics
curl http://localhost:8000/metrics | grep prediction

# View recent predictions
python scripts/view_predictions.py --last-hour
```

4. **Trigger Alerts**
```bash
# Simulate high error rate
python scripts/simulate_errors.py --error-rate 0.15

# Check alert status
curl http://localhost:8000/health
```

### Scenario 2: Model Lifecycle Management

#### Overview
Demonstrate complete model lifecycle from training to deployment.

#### Steps

1. **Train Multiple Models**
```bash
# Option A: Train using Docker containers (Recommended)
# The beam-runner container has all dependencies
docker-compose --profile beam run beam-runner python -m src.models.training.train \
    --experiment fraud_detection_baseline \
    --n-estimators 50

docker-compose --profile beam run beam-runner python -m src.models.training.train \
    --experiment fraud_detection_advanced \
    --n-estimators 200

# Option B: Use the training script
./scripts/demo/train_docker.sh

# Option C: Train locally (requires environment activation)
source .venv/Scripts/activate  # Windows
# source .venv/bin/activate    # Linux/macOS
python scripts/demo/quick_train_model.py
```

2. **Compare Models in MLflow**
```bash
# Open MLflow UI
open http://localhost:5000

# Navigate to experiments and compare metrics
# Look for accuracy, precision, recall, F1-score
```

3. **Deploy Best Model**
```bash
# Get model info
curl http://localhost:8000/models/fraud_detector

# Update model version
python scripts/update_model.py --model fraud_detector --version 2

# Verify model update
curl http://localhost:8000/models/fraud_detector
```

4. **A/B Test Models**
```bash
# Split traffic between models
python scripts/ab_test.py --model-a fraud_detector:1 --model-b fraud_detector:2 --split 50/50

# Monitor performance
curl http://localhost:8000/metrics | grep model_performance
```

### Scenario 3: Multi-Cloud Streaming

#### Overview
Show how the platform handles data from multiple cloud sources.

#### Steps

1. **Simulate Pub/Sub Messages**
```bash
# Start GCP Pub/Sub simulator
python scripts/simulate_pubsub.py --topic transactions --rate 50
```

2. **Simulate Kinesis Stream**
```bash
# Start AWS Kinesis simulator
python scripts/simulate_kinesis.py --stream ml-pipeline-features --rate 30
```

3. **Simulate Kafka Messages**
```bash
# Start Kafka simulator
python scripts/simulate_kafka.py --topic ml-predictions --rate 40
```

4. **Monitor Ingestion**
```bash
# Check ingestion metrics
curl http://localhost:8000/metrics | grep ingestion

# View processing lag
python scripts/monitor_lag.py
```

### Scenario 4: Performance Testing

#### Overview
Test system performance under various load conditions.

#### Steps

1. **Baseline Performance**
```bash
# Single request latency
time curl -X POST http://localhost:8000/predict -H "Content-Type: application/json" -d @sample_data/small/sample_request.json
```

2. **Load Testing**
```bash
# Install Apache Bench if not available
# sudo apt-get install apache2-utils  # Ubuntu
# brew install httpie  # macOS

# Test API performance
ab -n 1000 -c 10 -T application/json -p sample_data/small/sample_request.json http://localhost:8000/predict

# Or use custom load test script
python scripts/load_test.py --requests 1000 --concurrency 10
```

3. **Batch Performance**
```bash
# Test batch predictions
python scripts/test_batch_performance.py --batch-sizes 10,50,100,500,1000
```

4. **Monitor Resource Usage**
```bash
# Check container resource usage
docker stats

# View detailed metrics in Grafana
open http://localhost:3001/d/ml-pipeline-overview
```

## Key Demo Features

### Automatic Model Updates
The API automatically checks for new Production models every 60 seconds:
- No service restart required
- Zero-downtime model swapping
- Configurable via `MODEL_UPDATE_INTERVAL`
- Fallback to cached models if MLflow unavailable

### Model Versioning Flow
1. **Version 1**: Initial training → Production stage
2. **Version 2**: New training → Auto-increments version → Replaces v1 in Production
3. **Rollback**: Change stage in MLflow → API auto-detects within 60s

### Storage Verification
- Models stored in MinIO S3 bucket
- Accessible via MLflow UI and MinIO Console
- Direct S3 API access for integration

## 📊 Demo Data Sets

### Transaction Data
- **Sample size**: 1,000 transactions
- **Features**: amount, merchant_category, time, location, user_profile
- **Labels**: 0 (legitimate), 1 (fraudulent)
- **Location**: `sample_data/small/sample_transactions.json`

### User Features
- **Sample size**: 100 users
- **Demographics**: age, income, credit_score, location
- **Behavior**: transaction_patterns, preferred_merchants, typical_amounts
- **Location**: `sample_data/small/sample_user_features.json`

### Model Training Data
- **Size**: 10,000 labeled transactions
- **Split**: 70% train, 20% validation, 10% test
- **Generation**: `python scripts/generate_training_data.py`

## 🔍 Monitoring and Observability

### Key Metrics to Monitor

#### Application Metrics
- **Prediction latency**: P50, P95, P99 response times
- **Throughput**: Requests per second
- **Error rate**: Percentage of failed requests
- **Model accuracy**: Real-time accuracy tracking

#### Infrastructure Metrics
- **CPU usage**: Per container and total
- **Memory usage**: Used vs. available
- **Disk I/O**: Read/write operations
- **Network**: Ingress/egress traffic

#### Business Metrics
- **Fraud detection rate**: Percentage of fraud caught
- **False positive rate**: Legitimate transactions flagged
- **Cost savings**: Estimated fraud prevented
- **Processing volume**: Transactions processed per hour

### Grafana Dashboards

1. **ML Pipeline Overview**
   - System health summary
   - Key performance indicators
   - Recent alerts and issues

2. **API Performance**
   - Request latency distribution
   - Error rate trends
   - Throughput metrics

3. **Model Performance**
   - Prediction accuracy over time
   - Model drift detection
   - Feature importance changes

4. **Infrastructure Health**
   - Resource utilization
   - Service availability
   - Database performance

### Setting Up Alerts

```bash
# Configure email alerts
python scripts/setup_alerts.py --email your-email@company.com

# Test alert system
python scripts/test_alerts.py --alert high_latency
```

## 🛠️ Troubleshooting Common Issues

### Service Startup Issues

**Problem**: Services fail to start
```bash
# Check service logs
docker-compose logs api
docker-compose logs redis
docker-compose logs postgres

# Restart specific service
docker-compose restart api
```

**Problem**: Port conflicts
```bash
# Check what's using the ports
netstat -tulpn | grep :8000
netstat -tulpn | grep :5000

# Update docker-compose.yml if needed
```

### Database Connection Issues

**Problem**: Cannot connect to PostgreSQL
```bash
# Check database status
docker-compose exec postgres psql -U postgres -c "SELECT 1;"

# Reset database
docker-compose down -v
docker-compose up -d postgres
```

### Model Loading Issues

**Problem**: Models not found in MLflow
```bash
# Check MLflow server
curl http://localhost:5000/health

# List available models
curl http://localhost:5000/api/2.0/mlflow/registered-models/list

# Retrain model if needed
# Option 1: Use Docker training
./scripts/demo/train_docker.sh

# Option 2: Quick training in container
./scripts/demo/train_in_container.sh

# Option 3: Local training (requires environment)
python scripts/demo/quick_train_model.py
```

### Performance Issues

**Problem**: High latency
```bash
# Check resource usage
docker stats

# Scale API service
docker-compose up -d --scale api=3

# Check database connections
docker-compose exec postgres psql -U postgres -c "SELECT count(*) FROM pg_stat_activity;"
```

## 🌟 Advanced Demo Features

### 1. Real-time Model Retraining

```bash
# Enable continuous learning
python scripts/continuous_learning.py --enable

# Monitor model drift
python scripts/monitor_drift.py --threshold 0.1

# Trigger retraining
python scripts/retrain_model.py --trigger drift_detected
```

### 2. Feature Store Management

```bash
# Add new feature group
python scripts/add_feature_group.py --name user_social --features likes,shares,comments

# Update feature transformations
python scripts/update_transforms.py --feature amount --transform log_normalize

# Feature lineage tracking
python scripts/feature_lineage.py --feature risk_score
```

### 3. Multi-Model Serving

```bash
# Deploy multiple models
python scripts/deploy_model.py --name fraud_detector_v2 --version latest
python scripts/deploy_model.py --name anomaly_detector --version production

# Route traffic based on rules
python scripts/setup_routing.py --rules routing_rules.yaml

# Monitor model performance
python scripts/model_comparison.py --models fraud_detector_v1,fraud_detector_v2
```

## 📝 Demo Checklist

### Pre-Demo Setup
- [ ] Environment variables configured
- [ ] Docker services running
- [ ] Sample data loaded
- [ ] Initial model trained
- [ ] Health checks passing

### Demo Execution
- [ ] Live data ingestion demonstrated
- [ ] Real-time predictions working
- [ ] Monitoring dashboards visible
- [ ] Feature store operations shown
- [ ] Model management features presented

### Post-Demo Cleanup

Complete cleanup to free up disk space and remove demo artifacts:

#### 1. Stop All Services
```bash
# Stop and remove containers, networks, and volumes
docker-compose down -v

# Remove Docker images (optional - frees more space)
docker image rm $(docker image ls -q rt-ml-multicloud-platform*)

# Clean up unused Docker resources
docker system prune -f
```

#### 2. Clean Up Demo Data
```bash
# Remove generated demo data
rm -rf data/demo/
rm -rf mlruns/
rm -rf sample_data/small/training_data.csv

# Clean up logs (if cleanup script exists)
python scripts/cleanup_demo.py 2>/dev/null || echo "Cleanup script not found, skipping"
./scripts/archive_logs.sh 2>/dev/null || echo "Archive script not found, skipping"
```

#### 3. Python Environment Cleanup

**If you used Poetry:**
```bash
# Remove this project's virtual environment
poetry env remove python

# Optional: Remove Poetry completely (if you don't need it for other projects)
pip uninstall poetry

# Optional: Clean Poetry cache (frees significant space)
poetry cache clear pypi --all

# Optional: Remove all Poetry environments and cache
# Windows:
rm -rf "$APPDATA/pypoetry"
# Linux/macOS:
rm -rf ~/.cache/pypoetry
```

**If you used pip + venv:**
```bash
# Deactivate virtual environment (if active)
deactivate

# Remove virtual environment
rm -rf .venv

# Remove Poetry (installed temporarily for Docker compatibility)
pip uninstall poetry

# Optional: Remove Poetry cache
# Windows:
rm -rf "$APPDATA/pypoetry"
# Linux/macOS:
rm -rf ~/.cache/pypoetry
```

#### 4. Verify Cleanup
```bash
# Check Docker cleanup
docker ps -a
docker image ls
docker volume ls

# Check Python environment cleanup
which python  # Should not show project venv path
poetry env list  # Should not show this project (if Poetry still installed)

# Check disk space recovered
du -sh .  # Check project directory size
```

#### 5. Optional: Complete Project Removal
```bash
# If you want to remove the entire project
cd ..
rm -rf rt-ml-multicloud-platform

# Verify removal
ls | grep rt-ml-multicloud-platform  # Should return nothing
```

**Space Recovery Estimate:**
- Docker containers/images: ~2-5 GB
- Poetry virtual environment: ~500 MB - 1 GB
- Demo data and MLflow artifacts: ~50-100 MB
- Poetry cache (if cleared): ~200-500 MB

## 🎥 Demo Script Template

### Introduction (2 minutes)
"Today I'll demonstrate our real-time ML pipeline platform that processes transactions, detects fraud, and adapts to new patterns automatically."

### Architecture Overview (3 minutes)
"The platform consists of streaming ingestion, feature engineering, model serving, and monitoring components, all running on Docker with Kubernetes support."

### Live Demo (15 minutes)
1. **Data Flow** (5 min): Show data ingestion → feature engineering → prediction
2. **Model Management** (5 min): Train new model, compare versions, deploy
3. **Monitoring** (5 min): Real-time dashboards, alerts, performance metrics

### Q&A and Deep Dive (10 minutes)
Address technical questions about architecture, scalability, and deployment options.

## 📞 Support and Resources

- **Documentation**: [docs/](./README.md)
- **Issues**: [GitHub Issues](https://github.com/your-org/rt-ml-multicloud-platform/issues)
- **Discussions**: [GitHub Discussions](https://github.com/your-org/rt-ml-multicloud-platform/discussions)
- **Wiki**: [Project Wiki](https://github.com/your-org/rt-ml-multicloud-platform/wiki)

---

**Happy demoing! 🚀**