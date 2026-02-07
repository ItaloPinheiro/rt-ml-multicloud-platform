# Running the Demo

This guide walks you through a complete end-to-end demo of the platform, from data generation to model training and serving.

## Quick Start

The easiest way to run the demo is using the provided script:

```bash
./scripts/demo/local-demo/demo.sh
```

This script will:
1.  Generate synthetic fraud detection data.
2.  Train a Random Forest model.
3.  Register the model in MLflow.
4.  Wait for the API to load the new model.
5.  Send sample prediction requests.

## Step-by-Step Walkthrough

If you prefer to run steps manually:

### 1. Generate Data

```bash
python scripts/demo/local-demo/generate_data.py
```
This creates training data in `sample_data/demo/datasets/` and test requests in `sample_data/demo/requests/`.

### 2. Train Model

You can train the model locally or via Docker.

**Local:**
```bash
python scripts/demo/utilities/quick_train_model.py
```

**Docker:**
```bash
./scripts/demo/utilities/train_docker.sh
```

### 3. Verify in MLflow

Visit [http://localhost:5000](http://localhost:5000). You should see a new experiment `fraud_detection` and a registered model `fraud_detector`.

### 4. Make Predictions

**Single Prediction:**

```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d @sample_data/demo/requests/baseline.json
```

**Batch Prediction:**

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

### 5. Check Metrics

Visit Grafana at [http://localhost:3001](http://localhost:3001) to see the prediction latency and throughput.

## Advanced Scenarios

### Model Retraining

Try running the training script again with different parameters:

```bash
python scripts/demo/utilities/quick_train_model.py --n-estimators 200
```

The API will detect the new version (if tagged Production or if configured to use latest) and update automatically within ~60 seconds.

### Feature Store Interaction

You can inspect the Redis cache to see stored features:

```bash
docker exec -it redis redis-cli KEYS "features:*"
```
