# Infrastructure Demo (Local Kubernetes)

This guide details how to run the **Infrastructure Demo**, which verifies the Kubernetes configuration (Manifests, PVCs, Services, NodePorts) using a local Kubernetes cluster (e.g., Docker Desktop).

> **Purpose:** This demo validates that the production-like Kubernetes infrastructure is correctly configured before deploying to a remote cloud environment (like AWS EC2).

## Prerequisites

*   **Docker Desktop** installed and running.
*   **Kubernetes** enabled in Docker Desktop settings.
*   `kubectl` installed and configured to point to `docker-desktop` context.
*   `python` (3.9+) installed locally.

## Step-by-Step Workflow

### 1. Deploy Infrastructure

Use the provided helper script to build docker images and deploy the Kubernetes manifests.

```bash
# This script builds local images and applies k8s/overlays/ec2-local
bash scripts/test_local_k8s.sh
```

**What this does:**
*   Builds `ml-pipeline/api:v1.0.0` and `ml-pipeline/mlflow:v1.0.0` locally.
*   Creates the `ml-pipeline-prod` namespace.
*   Applies the Kustomize overlay `k8s/overlays/ec2-local` (which uses NodePorts for local access).

**Verify Deployment:**
```bash
kubectl get pods -n ml-pipeline-prod
# Wait until all pods are in STATUS: Running
```

### 2. Generate Data

Generate synthetic data for training and testing. This ensures the schema matches what the model verifies.

```bash
python scripts/demo/generate_data.py
```

*   **Training Data:** `sample_data/demo/datasets/fraud_detection.csv`
*   **Request Data:** `sample_data/demo/requests/baseline.json`

### 3. Train & Register Model

Run the adapted training script. This script acts as a client outside the cluster, communicating with the services via NodePorts.

```bash
# Trains model locally and logs to MLflow (localhost:30000)
python scripts/demo/test_local_k8s_train.py
```

**Key Actions:**
*   Connects to MLflow at `http://localhost:30000`.
*   Trains a Random Forest (wrapped in a `Pipeline` for schema consistency).
*   Logs metrics and artifacts to the MLflow server (which persists them to the PVC).
*   Registers the model as `fraud_detector` and promotes it to `Production`.

### 4. Verify API Prediction

Once the model is in `Production`, the API (checking for updates every 60s) will load it. You can trigger a manual restart to force an immediate update if needed:

```bash
kubectl rollout restart deployment ml-pipeline-api -n ml-pipeline-prod
kubectl rollout status deployment/ml-pipeline-api -n ml-pipeline-prod
```

**Send Prediction Request:**

```bash
# Using curl
curl -X POST http://localhost:30001/predict \
  -H "Content-Type: application/json" \
  -d @sample_data/demo/requests/baseline.json
```

**Expected Response (200 OK):**
```json
{
  "prediction": 0.0,
  "probabilities": [0.95, 0.05],
  "model_name": "fraud_detector",
  "model_version": "1",
  ...
}
```

## Access Points

| Service | Local URL | Description |
| :--- | :--- | :--- |
| **Model API** | [http://localhost:30001/docs](http://localhost:30001/docs) | Swagger UI for testing endpoints |
| **MLflow UI** | [http://localhost:30000](http://localhost:30000) | Validating experiments and artifacts |
| **Grafana** | [http://localhost:30002](http://localhost:30002) | (If monitoring is deployed) Logs & Metrics |
| **Prometheus**| [http://localhost:30090](http://localhost:30090) | (If monitoring is deployed) Raw metrics |

## Troubleshooting

*   **API 500 Error (Schema Mismatch):** Ensure you ran `generate_data.py` recently and that `test_local_k8s_train.py` uses the `Pipeline` (StandardScaler + Model).
*   **Connection Refused:** Check if pods are running (`kubectl get pods -n ml-pipeline-prod`).
*   **MLflow Artifacts Missing:** Verify the PVC mount in `k8s/overlays/ec2-local` matches the MLflow server arguments (`--artifacts-destination`).

## Cleanup

To remove all resources:

```bash
kubectl delete namespace ml-pipeline-prod
```
