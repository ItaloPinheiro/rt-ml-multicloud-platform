# Infrastructure Demo (Local Kubernetes)

This guide details how to run the **Infrastructure Demo**, which verifies the Kubernetes configuration (Manifests, PVCs, Services, NodePorts) using a local Kubernetes cluster (e.g., Docker Desktop).

> **Purpose:** This demo validates that the production-like Kubernetes infrastructure is correctly configured before deploying to a remote cloud environment (like AWS EC2).

## Prerequisites

*   **Docker Desktop** installed and running.
*   **Kubernetes** enabled in Docker Desktop settings.
*   `kubectl` installed and configured to point to `docker-desktop` context.
*   `python` (3.9+) installed locally.

## Step-by-Step Workflow

The following commands describe the process to verify the infrastructure.

### 1. Clean Slate

To start fresh with model version 1, you must remove both Docker containers and the Kubernetes namespace (which contains the PVC data).

Stop any running "local demo" Docker containers:
```bash
docker ps -aq --filter "name=ml-" | xargs -r docker rm -f
```

Delete the Kubernetes namespace (⚠️ **Deletes all MLflow experiments and model data**):
```bash
kubectl delete namespace ml-pipeline-prod --ignore-not-found
```

> [!NOTE]
> The K8s namespace contains PersistentVolumeClaims (PVCs) that store MLflow registry and MinIO data. Deleting the namespace resets model versions to start from v1.

### 2. Deploy Infrastructure

Use the provided helper script to build docker images and deploy the Kubernetes manifests (applies `k8s/overlays/ec2-local`).

```bash
bash scripts/demo/demo-local-k8s/demo-local-k8s.sh
```

Verify that the `ml-pipeline-prod` namespace was created and all services are running.

```bash
kubectl get pods -n ml-pipeline-prod --watch
```
*Wait for all pods to show status "Running".*

### 3. Train & Register Model (Version 1)
Run the Python script to train the initial model locally and log it to the K8s-hosted MLflow service.

```bash
python scripts/demo/demo-local-k8s/train.py
```

This script will:
*   Train a Random Forest model (n_estimators=100).
*   Log metrics and artifacts to MLflow.
*   Promote the model to "Production".

### 4. Verify API Prediction (Version 1)

Test the API to ensure it picked up the new Production model (Version 1).

```bash
curl -X POST http://localhost:30001/predict \
  -H "Content-Type: application/json" \
  -d @data/sample/demo/requests/baseline_prediction_request.json | python -m json.tool
```

### 5. Train & Upgrade Model (Version 2)
Now, simulate a model improvement cycle by training a new version with different hyperparameters.

```bash
python scripts/demo/demo-local-k8s/train.py --n-estimators 200
```

This step verifies:
1.  **Continuous Deployment**: The new model is automatically detected by the running API.
2.  **Zero-Downtime**: The API serves traffic while switching versions.
3.  **Latency**: The script asserts the API responds quickly (<200ms) after the update.

### 6. Final API Check

Confirm the API is serving Version 2 by sending a test request:

```bash
curl -X POST http://localhost:30001/predict \
  -H "Content-Type: application/json" \
  -d @data/sample/demo/requests/improved_prediction_request.json | python -m json.tool
```

Verify that the response contains `model_version: 2` (or higher if you ran multiple training iterations).



| Service | Local URL | Description |
| :--- | :--- | :--- |
| **Model API** | [http://localhost:30001/docs](http://localhost:30001/docs) | Swagger UI for testing endpoints |
| **MLflow UI** | [http://localhost:30000](http://localhost:30000) | Validating experiments and artifacts |
| **Grafana** | [http://localhost:30002](http://localhost:30002) | Logs & Metrics |
| **Prometheus**| [http://localhost:30090](http://localhost:30090) | Raw metrics |

## Cleanup

To remove the simulated production environment and delete the namespace:

```bash
kubectl delete namespace ml-pipeline-prod
```
