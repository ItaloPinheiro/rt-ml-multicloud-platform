# ML Pipeline Platform Demo

This demo showcases the complete ML pipeline workflow including model training, versioning, and real-time serving.

## Prerequisites

- Docker & Docker Compose installed
- Python 3.11+ with Poetry
- 8GB+ RAM
- 10GB free disk space

## Setup

### 1. Install Dependencies

```bash
# Install Poetry if needed
pip install poetry

# Install project dependencies
poetry install
poetry shell
```

### 2. Start Services

```bash
# Copy environment template
cp .env.example .env

# Start all services
docker-compose up -d

# Wait for services (30-60 seconds)
sleep 30

# Verify health
curl http://localhost:8000/health
```

## Running the Demo

### Quick Demo

Run the complete demo script which trains a model and tests predictions:

```bash
./scripts/demo/demo.sh
```

This script:
1. Generates sample data
2. Trains a fraud detection model
3. Registers it in MLflow
4. Tests predictions via the API
5. Shows model metrics

### Step-by-Step Demo

#### 1. Generate Sample Data

```bash
python scripts/demo/generate_data.py
```

Creates:
- `sample_data/demo/datasets/fraud_detection.csv` - Training data
- `sample_data/demo/requests/*.json` - Test requests

#### 2. Train Model

Option A - Using Docker container:
```bash
./scripts/demo/utilities/train_docker.sh
```

Option B - Local training:
```bash
python scripts/demo/utilities/quick_train_model.py
```

#### 3. Verify Model in MLflow

Open MLflow UI: http://localhost:5000
- Click "Models" tab
- View "fraud_detector" model
- Check version and metrics

#### 4. Test Predictions

Single prediction:
```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d @sample_data/demo/requests/baseline.json
```

Batch prediction:
```bash
curl -X POST http://localhost:8000/predict/batch \
  -H "Content-Type: application/json" \
  -d '{
    "instances": [
      {"amount": 100.0, "merchant_category": "grocery"},
      {"amount": 500.0, "merchant_category": "electronics"}
    ],
    "model_name": "fraud_detector"
  }'
```

#### 5. Monitor Performance

Check metrics:
```bash
curl http://localhost:8000/metrics | grep prediction
```

View Grafana dashboards: http://localhost:3001 (admin/admin123)

## Key Features Demonstrated

### Automatic Model Updates
The API automatically checks for new models every 60 seconds. When you train a new version and promote it to "Production" in MLflow, the API loads it automatically without restart.

### Model Versioning
1. Train initial model → Version 1
2. Train improved model → Version 2
3. MLflow tracks all versions with metrics
4. API serves the latest "Production" model

### Performance Optimization
- Redis caching for features and predictions
- Batch prediction support
- Model pre-loading and caching
- Async request handling

## Service URLs

| Service | URL | Credentials |
|---------|-----|-------------|
| API Docs | http://localhost:8000/docs | - |
| MLflow | http://localhost:5000 | - |
| Grafana | http://localhost:3001 | admin/admin123 |
| MinIO | http://localhost:9001 | minioadmin/minioadmin123 |
| Prometheus | http://localhost:9090 | - |

## Troubleshooting

### Services Not Starting

Check logs:
```bash
docker-compose logs -f model-api
docker-compose logs -f mlflow-server
```

Restart services:
```bash
docker-compose restart model-api
```

### Model Not Found

Ensure model is trained:
```bash
# List models in MLflow
curl http://localhost:5000/api/2.0/mlflow/registered-models/list

# Retrain if needed
python scripts/demo/utilities/quick_train_model.py
```

### High Latency

Check resource usage:
```bash
docker stats
```

Scale API if needed:
```bash
docker-compose up -d --scale model-api=3
```

## Cleanup

Stop services and clean up:
```bash
# Stop services
docker-compose down

# Remove volumes (deletes data)
docker-compose down -v

# Clean up demo data
rm -rf sample_data/generated/
rm -rf mlruns/
```

## Advanced Usage

### Custom Model Training

Train with custom parameters:
```bash
python scripts/demo/utilities/quick_train_model.py \
  --n-estimators 200 \
  --max-depth 10 \
  --model-name custom_model
```

### Load Testing

Test API performance:
```bash
# Install Apache Bench
apt-get install apache2-utils  # Ubuntu
brew install httpie  # macOS

# Run load test
ab -n 1000 -c 10 -T application/json \
  -p sample_data/demo/requests/baseline.json \
  http://localhost:8000/predict
```

### Feature Store Operations

View cached features:
```bash
# Connect to Redis
docker exec -it redis redis-cli

# List keys
KEYS feature:*

# Get feature value
GET feature:user_123
```

## Next Steps

1. Explore the API documentation at http://localhost:8000/docs
2. Train models with different algorithms
3. Configure production deployment
4. Set up monitoring alerts in Grafana
5. Test streaming data ingestion