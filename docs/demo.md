# ML Pipeline Platform Demo Guide

This guide provides step-by-step instructions for running a complete demo of the real-time ML pipeline platform, from initial setup to making predictions and monitoring the system.

## 🎯 Demo Overview

The demo will showcase:
- **Real-time data ingestion** from multiple sources
- **Feature engineering** with Apache Beam
- **Model training** and registration with MLflow
- **Real-time predictions** via FastAPI
- **Monitoring and alerting** with Prometheus/Grafana

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

### Optional (for cloud deployment)
- kubectl
- gcloud CLI (for GCP)
- aws CLI + eksctl (for AWS)

## 🚀 Quick Start Demo (5 minutes)

### 1. Clone and Setup

```bash
# Clone the repository
git clone https://github.com/your-org/rt-ml-multicloud-platform.git
cd rt-ml-multicloud-platform

# Setup environment
./scripts/setup.sh

# Start all services
docker-compose up -d

# Wait for services to be ready (check with)
./scripts/health-check.sh
```

### 2. Load Sample Data

```bash
# Load sample transactions and features
python scripts/load_sample_data.py

# Verify data loading
curl http://localhost:8000/health
```

### 3. Train Initial Model

```bash
# Run model training
python src/models/training/train_fraud_model.py

# Check MLflow UI
open http://localhost:5000
```

### 4. Make Predictions

```bash
# Single prediction
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

### Scenario 1: Fraud Detection Pipeline

#### Overview
Simulate a real-time fraud detection system processing credit card transactions.

#### Steps

1. **Start Stream Simulation**
```bash
# Generate synthetic transaction stream
python scripts/simulate_transactions.py --rate 100 --duration 300
```

2. **Monitor Feature Store**
```bash
# Check feature store metrics
curl http://localhost:8000/metrics | grep feature_store

# View stored features
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
# Train baseline model
python src/models/training/train_fraud_model.py --model-type logistic

# Train advanced model
python src/models/training/train_fraud_model.py --model-type xgboost

# Train neural network
python src/models/training/train_fraud_model.py --model-type neural
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
python src/models/training/train_fraud_model.py
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
- [ ] Stop all services: `docker-compose down`
- [ ] Clean up test data: `python scripts/cleanup_demo.py`
- [ ] Archive demo logs: `./scripts/archive_logs.sh`

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