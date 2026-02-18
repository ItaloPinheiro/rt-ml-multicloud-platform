# Local Demo Reproduction

This document details the exact steps and commands used to successfully execute the local End-to-End Demo on a Windows environment.

## Executive Summary

We successfully ran the local demonstration of the ML Platform, covering:
1.  Infrastructure startup (MLflow, Redis, MinIO, API, Monitoring).
2.  Training of an initial fraud detection model (v1).
3.  Live prediction serving with v1.
4.  Retraining and auto-promotion of an improved model (v2).
5.  Zero-downtime API update and prediction verification with v2.

## Reproduction Steps & Commands

The following commands were executed in **Bash** (unless otherwise noted) from the repository root: `c:\Users\italo\github\rt-ml-multicloud-platform`.

### Step 1: Clean Slate
Ensure no conflicting containers, networks, or volumes exist. This guarantees starting with model version 1.

Remove existing containers:
```bash
docker ps -aq --filter "name=ml-" | xargs -r docker rm -f
```

Remove named volumes (⚠️ **Caution: Deletes all MLflow experiments and model data**):
```bash
docker volume rm local_mlflow_db_data local_mlflow_minio_data local_redis_data -f 2>/dev/null
docker volume prune -f
docker network prune -f
```

> [!NOTE]
> Standard `docker volume prune` only removes **anonymous** volumes. Named volumes like `local_mlflow_db_data` must be explicitly removed to reset model versions to v1.

### Step 2: Start Infrastructure
Launched the core services using the fixed Docker Compose files.

```bash
docker-compose -f ops/local/docker-compose.yml -f ops/local/docker-compose.override.yml up -d
```

*Wait ~30-60 seconds for services to initialize.*

### Step 3: Train Model Version 1 (Baseline)
Used the `beam-runner` container to execute the training script.

Start the runner container:
```bash
docker-compose -f ops/local/docker-compose.yml -f ops/local/docker-compose.override.yml --profile beam up -d beam-runner
```

Execute training script:
```bash
docker exec ml-beam-runner sh -c "python -m src.models.training.train --data-path /app/data/sample/demo/datasets/fraud_detection.csv --mlflow-uri http://mlflow-server:5000 --experiment fraud_detection --model-name fraud_detector"
```

### Step 4: Verify Model V1 Prediction
Confirmed the model was loaded and capable of predicting.

Check loaded model status:
```bash
curl -s http://localhost:8000/models | jq .
```

Make a prediction (Baseline request):
```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d @data/sample/demo/requests/baseline_prediction_request.json
```

### Step 5: Train Model Version 2 (Improved)
Trained a new version with more estimators (`--n-estimators 150`).

```bash
docker exec ml-beam-runner sh -c "python -m src.models.training.train --data-path /app/data/sample/demo/datasets/fraud_detection.csv --mlflow-uri http://mlflow-server:5000 --experiment fraud_detection --model-name fraud_detector --n-estimators 150"
```

### Step 6: Verify Auto-Promotion
The API polls for updates every 60 seconds (default). Checked that V2 was loaded.

Check loaded model status (Wait for version to change to "2"):
```bash
curl -s http://localhost:8000/models | jq .
```

### Step 7: Verify Model V2 Prediction
Tested predictions with the new model version using the corrected "improved" payload.

```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d @data/sample/demo/requests/improved_prediction_request.json
```

## Verification Results

*   **API Health**: `http://localhost:8000/health` -> `{"status": "healthy"}`
*   **Model Serving**: Successfully served predictions for both V1 and V2 models.
*   **Latency**: First prediction ~200ms (uncached), subsequent predictions <10ms (cached).
*   **MLflow**: Confirmed experiment run tracking and artifact storage in MinIO.
