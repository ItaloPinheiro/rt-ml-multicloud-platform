# Data Pipeline Execution Plan

This document provides execution plans for utilizing the `data/` folder structure in the RT ML multicloud platform. These workflows demonstrate practical use cases that justify maintaining the data directories for ML pipeline operations.

## Overview

The `data/` folder serves as the local data staging and processing workspace with three key directories:
- `data/raw/` - Raw ingested data from streaming sources
- `data/features/` - Processed feature sets ready for ML models
- `data/predictions/` - Model prediction outputs and logs

## Execution Plan 1: End-to-End Data Processing Pipeline

### Objective
Process streaming transaction data through the complete ML pipeline from ingestion to prediction output.

### Prerequisites
```bash
# Ensure all services are running
docker-compose up -d

# Verify services are healthy
./scripts/demo/demo-local/demo.sh
```

### Step 1: Raw Data Ingestion
```bash
# 1.1 Start streaming data ingestion from Kafka/Redpanda
python src/ingestion/kafka/consumer.py --topic transactions --output-dir data/raw/

# 1.2 Simulate real-time transactions (alternative for testing)
python scripts/demo/generate_sample_transactions.py --output data/raw/transactions_$(date +%Y%m%d_%H%M%S).json

# 1.3 Verify raw data ingestion
ls -la data/raw/
tail -f data/raw/transactions_latest.json
```

### Step 2: Feature Engineering with Apache Beam
```bash
# 2.1 Process raw transactions into features
python src/feature_engineering/beam/pipelines.py \
  --input data/raw/transactions_*.json \
  --output data/features/transaction_features \
  --runner DirectRunner

# 2.2 Generate user aggregation features
python src/feature_engineering/beam/transforms.py \
  --input data/raw/ \
  --output data/features/user_aggregations \
  --window-size 24h

# 2.3 Verify feature generation
ls -la data/features/
head data/features/transaction_features-00000-of-00001
```

### Step 3: Feature Store Population
```bash
# 3.1 Load features into Redis + PostgreSQL feature store
python scripts/feature_store/load_features.py \
  --input-dir data/features/ \
  --feature-group transaction_features

# 3.2 Verify feature store population
redis-cli -h localhost -p 6379 KEYS "feature:*" | head -10
python scripts/feature_store/query_features.py --user-id user_123
```

### Step 4: Model Training with Generated Features
```bash
# 4.1 Train model using processed features
python src/models/training/train_fraud_detection.py \
  --features-path data/features/transaction_features \
  --model-output models/fraud_detection_v$(date +%Y%m%d)

# 4.2 Register model in MLflow
python scripts/models/register_model.py \
  --model-path models/fraud_detection_v$(date +%Y%m%d) \
  --model-name fraud_detection
```

### Step 5: Real-time Prediction and Logging
```bash
# 5.1 Start model serving API
# (API should already be running via docker-compose)

# 5.2 Generate predictions and log outputs
python scripts/prediction/batch_predict.py \
  --input data/features/transaction_features \
  --output data/predictions/batch_predictions_$(date +%Y%m%d_%H%M%S).json

# 5.3 Real-time prediction with logging
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d @sample_data/small/sample_transactions.json \
  | tee data/predictions/realtime_prediction_$(date +%Y%m%d_%H%M%S).json
```

### Step 6: Monitoring and Analysis
```bash
# 6.1 Analyze prediction outputs
python scripts/monitoring/analyze_predictions.py \
  --predictions-dir data/predictions/ \
  --output-report data/predictions/analysis_report.json

# 6.2 Generate monitoring metrics
python scripts/monitoring/generate_metrics.py \
  --data-dir data/ \
  --prometheus-output monitoring/custom_metrics.txt
```

## Execution Plan 2: Batch Feature Engineering Workflow

### Objective
Process historical data in batches to populate feature store and train models.

### Workflow Steps
```bash
# 1. Historical data ingestion
python scripts/data/ingest_historical.py \
  --source s3://your-bucket/historical-transactions/ \
  --output data/raw/historical/

# 2. Batch feature engineering
python src/feature_engineering/beam/batch_pipeline.py \
  --input "data/raw/historical/*.json" \
  --output data/features/historical_features \
  --runner DataflowRunner  # Or DirectRunner for local

# 3. Feature validation and quality checks
python scripts/data/validate_features.py \
  --input data/features/historical_features \
  --schema configs/feature_schema.yaml \
  --output data/features/validated/

# 4. Bulk load to feature store
python scripts/feature_store/bulk_load.py \
  --input data/features/validated/ \
  --batch-size 10000
```

## Execution Plan 3: Model Performance Monitoring Pipeline

### Objective
Monitor model performance using prediction logs and generate drift detection alerts.

### Workflow Steps
```bash
# 1. Collect prediction logs
python scripts/monitoring/collect_prediction_logs.py \
  --api-logs /var/log/model-api/ \
  --output data/predictions/collected_logs/

# 2. Analyze prediction drift
python scripts/monitoring/drift_detection.py \
  --baseline data/features/training_baseline \
  --current data/predictions/collected_logs/ \
  --output data/predictions/drift_analysis.json

# 3. Generate performance reports
python scripts/monitoring/performance_report.py \
  --predictions data/predictions/ \
  --ground-truth data/raw/labeled_data/ \
  --output data/predictions/performance_report.html
```

## Execution Plan 4: Data Pipeline Testing and Validation

### Objective
Test the complete data pipeline with sample data to ensure all components work correctly.

### Workflow Steps
```bash
# 1. Copy sample data to raw folder for processing
cp sample_data/small/sample_transactions.json data/raw/test_transactions.json
cp sample_data/small/sample_user_features.json data/raw/test_user_features.json

# 2. Run mini feature engineering pipeline
python src/feature_engineering/beam/transforms.py \
  --input data/raw/test_*.json \
  --output data/features/test_features \
  --runner DirectRunner

# 3. Test feature store integration
python scripts/test/test_feature_store_integration.py \
  --test-features data/features/test_features

# 4. Test prediction pipeline
python scripts/test/test_prediction_pipeline.py \
  --input data/features/test_features \
  --output data/predictions/test_predictions.json

# 5. Validate end-to-end pipeline
python scripts/test/validate_e2e_pipeline.py \
  --data-dir data/ \
  --report data/pipeline_validation_report.json
```

## Required Scripts and Components

To execute these plans, the following components need to be implemented:

### Data Ingestion Scripts
- `scripts/demo/generate_sample_transactions.py` - Generate sample transaction data
- `scripts/data/ingest_historical.py` - Ingest historical data from cloud storage

### Feature Engineering Scripts
- `src/feature_engineering/beam/batch_pipeline.py` - Batch processing pipeline
- `scripts/data/validate_features.py` - Feature validation and quality checks

### Feature Store Scripts
- `scripts/feature_store/load_features.py` - Load features into store
- `scripts/feature_store/bulk_load.py` - Bulk loading for historical data
- `scripts/feature_store/query_features.py` - Query features from store

### Model Training and Serving Scripts
- `scripts/models/register_model.py` - Register models in MLflow
- `scripts/prediction/batch_predict.py` - Batch prediction processing

### Monitoring Scripts
- `scripts/monitoring/analyze_predictions.py` - Analyze prediction outputs
- `scripts/monitoring/generate_metrics.py` - Generate custom metrics
- `scripts/monitoring/drift_detection.py` - Model drift detection
- `scripts/monitoring/performance_report.py` - Performance reporting

### Testing Scripts
- `scripts/test/test_feature_store_integration.py` - Feature store testing
- `scripts/test/test_prediction_pipeline.py` - Prediction pipeline testing
- `scripts/test/validate_e2e_pipeline.py` - End-to-end validation

## Data Folder Usage Patterns

### Development Workflow
```bash
# Daily development cycle
data/raw/$(date +%Y%m%d)/           # Today's raw data
data/features/$(date +%Y%m%d)/      # Today's processed features
data/predictions/$(date +%Y%m%d)/   # Today's predictions
```

### Production Workflow
```bash
# Timestamped processing
data/raw/hourly/$(date +%Y%m%d_%H)/         # Hourly raw data batches
data/features/hourly/$(date +%Y%m%d_%H)/    # Hourly feature processing
data/predictions/hourly/$(date +%Y%m%d_%H)/ # Hourly prediction outputs
```

### Data Retention Strategy
```bash
# Cleanup old data (example retention: 7 days)
find data/raw/ -type f -mtime +7 -delete
find data/features/ -type f -mtime +7 -delete
find data/predictions/ -type f -mtime +30 -delete  # Keep predictions longer
```

## Environment Variables for Data Processing

Add to your `.env` file:
```bash
# Data processing configuration
DATA_RETENTION_DAYS=7
BATCH_SIZE=10000
FEATURE_VALIDATION_ENABLED=true
PREDICTION_LOGGING_ENABLED=true

# Processing directories
RAW_DATA_DIR=data/raw
FEATURES_DATA_DIR=data/features
PREDICTIONS_DATA_DIR=data/predictions
```

## Integration with Docker Compose

The data folders are already mounted in docker-compose.yml:
```yaml
volumes:
  - ./data:/app/data
```

This allows all containerized services to read/write to the data directories consistently.

## Monitoring Data Folder Usage

Add these metrics to your monitoring setup:

```python
# Prometheus metrics for data folder monitoring
data_folder_size_bytes = Gauge('data_folder_size_bytes', 'Size of data folders', ['folder'])
data_processing_duration_seconds = Histogram('data_processing_duration_seconds', 'Data processing time', ['pipeline'])
data_files_processed_total = Counter('data_files_processed_total', 'Files processed', ['type'])
```

## Conclusion

These execution plans demonstrate practical use cases for the `data/` folder structure, ensuring that:

1. **Raw data ingestion** has a clear landing zone
2. **Feature engineering** has dedicated workspace
3. **Prediction outputs** are properly logged and stored
4. **Data lineage** is maintained through the pipeline
5. **Monitoring and validation** can track data quality

The data folders are essential for local development, testing, and small-scale production deployments where file-based data staging is appropriate before scaling to cloud-native storage solutions.