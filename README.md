# Real-time ML Pipeline Platform

Production-ready machine learning pipeline that processes streaming data from multiple cloud sources, performs real-time feature engineering with Apache Beam, manages models with MLflow, and serves predictions via FastAPI.

## 🏗️ Architecture Overview

```
Stream Sources → Apache Beam → Feature Store → MLflow → FastAPI → Monitoring
    ↓                ↓            ↓              ↓         ↓          ↓
Pub/Sub/Kinesis  Processing   BigQuery/Redis  Registry   API    Prometheus
                              /Redshift                          + Grafana
```

## 🎯 Key Features

- **Multi-cloud streaming ingestion** (GCP Pub/Sub, AWS Kinesis, Kafka)
- **Apache Beam** feature engineering with auto-scaling
- **MLflow** complete model lifecycle management
- **FastAPI** high-performance model serving
- **Real-time monitoring** with Prometheus and Grafana
- **Redis** feature store for low-latency serving
- **Docker Compose** for local development

## 🚀 Quick Start

```bash
# 1. Setup environment
./scripts/setup.sh

# 2. Start all services
docker-compose up -d

# 3. Run demo pipeline
./scripts/demo.sh

# 4. Test predictions
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"features": {"amount": 250.00, "merchant_category": "electronics"}}'
```

## 📊 Use Cases

- **Fraud Detection**: Real-time transaction analysis
- **Recommendation Systems**: Live user behavior processing
- **Anomaly Detection**: Streaming sensor data analysis
- **Risk Assessment**: Financial data processing

## 🛠️ Technology Stack

- **Languages**: Python 3.11+
- **Streaming**: Apache Beam, Kafka, Pub/Sub, Kinesis
- **ML**: MLflow, scikit-learn, XGBoost, LightGBM
- **API**: FastAPI, Pydantic
- **Storage**: Redis, PostgreSQL, MinIO
- **Monitoring**: Prometheus, Grafana
- **Infrastructure**: Docker, Kubernetes

## 📦 Project Status

🏗️ **Under Development** - Building incrementally with production-ready components

## 📄 License

MIT License - see LICENSE file for details