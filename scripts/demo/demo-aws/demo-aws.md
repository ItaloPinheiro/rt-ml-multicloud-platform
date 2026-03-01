# AWS Cloud Demo Guide

This guide details how to run the End-to-End ML Platform demo against a live AWS EC2 instance. 
Unlike the local demo which runs everything on your machine, this workflow runs the **training and validaton** scripts locally on your laptop, but they communicate with the **remote infrastructure** (MLflow, Redis, API) deployed on AWS.

> **Target Environment**: AWS EC2 Instance (Ubuntu + K3s)

## Prerequisites

*   **Python 3.13+** installed locally.
*   **Bash** (recommended) or Git Bash on Windows.
*   **AWS CLI** installed and configured.
*   Project dependencies installed (`poetry install`).
*   The AWS instance must be running and fully bootstrapped.

## Step-by-Step Workflow

### 1. Populate Secrets

The required secrets (GitHub PAT and App Secrets) are created (empty) by Terraform when you provision the infrastructure. Before running the demo, you must **populate** them with the actual values using the local script.

```bash
./local/manage_secrets.sh
```

### 2. Configure Connection

Since the EC2 instance IP is dynamic, we use the AWS CLI to fetch the current public IP and set the environment variables automatically.

Get the Public IP of the running demo instance
```bash
INSTANCE_IP=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=rt-ml-platform-demo-instance" "Name=instance-state-name,Values=running" \
    --query "Reservations[*].Instances[*].PublicIpAddress" \
    --output text) && echo $INSTANCE_IP
```

Set Environment Variables
```bash
export MLFLOW_TRACKING_URI="http://${INSTANCE_IP}:30500"
export API_URL="http://${INSTANCE_IP}:30800"
```

### 3. Verify Instance Setup

Before training, ensure the EC2 instance has finished running its bootstrap script (installing K3s, Docker, etc.).

**Check User Script Logs:**
```bash
ssh -i ml-pipeline-debug.pem ubuntu@$INSTANCE_IP "sudo cat /var/log/user-data.log"
```

**Re-run Bootstrap (if needed):**
If the setup failed or you need to re-trigger the script:
```bash
ssh -i ml-pipeline-debug.pem ubuntu@$INSTANCE_IP "sudo /var/lib/cloud/instance/scripts/part-001"
```

**Verify Services:**
Once the script completes, ensure the platform pods are running:
```bash
ssh -i ml-pipeline-debug.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl get pods -n ml-pipeline"
```
*   You should see `ml-pipeline-api` and `ml-pipeline-mlflow` with status `Running`.

### 4. Upload Training Data to S3

Upload the demo dataset to the S3 training bucket (created by Terraform):

```bash
aws s3 cp data/sample/demo/datasets/fraud_detection.csv \
  s3://rt-ml-platform-training-data-demo/datasets/fraud_detection.csv
```

Verify the upload:
```bash
aws s3 ls s3://rt-ml-platform-training-data-demo/datasets/
```

### 5. Train Model Version 1 (Baseline)

Training now runs as a **K8s Job inside the cluster**, not on your laptop.
The training Job downloads data from S3, trains, and registers the model in MLflow.
The evaluation gate then compares it against the current champion and promotes only if it's better.

We start with a **weak baseline** model: few estimators and shallow trees (max depth 1). This model will have decent accuracy (~80%) but poor fraud detection (f1 near 0) because the shallow trees can't learn complex fraud patterns.

```bash
export EC2_IP=$INSTANCE_IP
./scripts/demo/demo-aws/trigger-training.sh --n-estimators 10 --max-depth 1 --auto-promote
```

> We use `--auto-promote` for v1 since there is no champion to compare against yet.

**Other training options:**
- **GitHub Actions (CI/CD path):** Actions -> "Train Model" -> Run workflow
- **Legacy local training:** `python scripts/demo/demo-aws/train.py`

**What to expect:**
*   Training Job runs inside the cluster (~1-2 minutes)
*   Model v1 is promoted as the first champion (no prior model to compare against)
*   API auto-detects the new production model within 10 seconds

### 6. Verify API Prediction (Version 1)

Send a prediction request to the remote API to confirm it is serving the model:

```bash
curl -X POST "$API_URL/predict" \
  -H "Content-Type: application/json" \
  -d @data/sample/demo/requests/baseline_prediction_request.json | python -m json.tool
```

*   **Success Criteria**: Response contains `"model_version": "1"`.

### 7. Train & Upgrade Model (Version 2 — Improved)

Now train a **stronger model** with more estimators and unlimited tree depth:

```bash
./scripts/demo/demo-aws/trigger-training.sh --n-estimators 200
```

**What happens:**
1.  Training Job runs with 200 estimators and unlimited depth (vs 10 trees at depth 1 in v1).
2.  Evaluation gate compares v2 against v1 champion on **accuracy** and **f1_score**.
3.  v2 will have better accuracy (~82% vs ~81%) and much better f1 (~0.40 vs ~0.00), so it gets promoted.

> **Tip:** You can also try `--class-weight balanced` to tell the classifier to pay more attention to the minority fraud class, trading some accuracy for better recall.

> **How the evaluation gate decides:** The challenger must meet a minimum accuracy threshold (0.80) AND beat the champion on both accuracy and f1_score. See `src/models/evaluation/evaluate_and_promote.py` for details.

### 8. Verify Auto-Promotion (Zero-Downtime Deployment)

The API polls MLflow every **10 seconds** for changes to the "production" alias.

Check the model version:
```bash
curl -X POST "$API_URL/predict" \
  -H "Content-Type: application/json" \
  -d @data/sample/demo/requests/baseline_prediction_request.json | python -m json.tool
```

*   **Success Criteria**: Response switches to `"model_version": "2"` without any downtime.

### Training Pipeline Architecture

```
[S3 Bucket] --> [Init Container: download data] --> [Training Job: train model]
                                                          |
                                                   [Register in MLflow]
                                                          |
                                               [Evaluation Job: compare vs champion]
                                                          |
                                                   [Promote if better]
                                                          |
                                               [API auto-detects new model]
```

---

## Accessing Dashboards

You can monitor the platform status via these URLs (replace hardcoded IPs with the dynamic IP):

| Service | Port | Description |
| :--- | :--- | :--- |
| **MLflow UI** | `30500` | http://$INSTANCE_IP:30500 |
| **Grafana** | `30300` | http://$INSTANCE_IP:30300 |
| **Prometheus**| `30900` | http://$INSTANCE_IP:30900 |
| **API Docs** | `30800` | http://$INSTANCE_IP:30800/docs |

### Navigating MLflow 3.x UI

MLflow 3.x introduces a redesigned UI with two top-level tabs: **GenAI** and **Model training**.

- **Model training** tab is the correct view for this demo. Click it to see experiments, runs, metrics, and the model registry for sklearn training runs.
- **GenAI** tab (with "Usage", "Quality", "Tool calls" sub-tabs) is designed for LLM/GenAI workloads that use MLflow Tracing. These tabs will always appear empty for traditional ML training runs — this is expected behavior, not a bug.

**Common navigation:**
1. **View experiment runs**: Click "Model training" -> select the `fraud_detection` experiment -> see all runs with metrics
2. **View model registry**: Click "Models" in the left sidebar -> see registered models, versions, and aliases
3. **Compare runs**: Select multiple runs from the experiment table -> click "Compare"

### Grafana

Access Grafana at `http://$INSTANCE_IP:30300`.

- **Dashboards**: Navigate to Dashboards -> Browse to find the pre-provisioned dashboards:
  - Applications Uptime and Health
  - Model Performance Monitoring
  - Feature Store Performance
  - Resource Utilization
  - Error Tracking and Alerts
  - ML Pipeline Overview

**Example dashboard URL** (replace `$INSTANCE_IP`):
```
http://$INSTANCE_IP:30300/d/apps-uptime/applications-uptime-and-health?orgId=1&refresh=1m
```

### Prometheus

Access Prometheus at `http://$INSTANCE_IP:30900`.

**Key metrics to query:**
- `up{job="ml-pipeline-api-service"}` — API availability (1 = up, 0 = down)
- `ml_predictions_total` — Total prediction requests served
- `ml_prediction_latency_seconds` — Prediction latency histogram
- `ml_dependency_health{dependency="mlflow"}` — MLflow connectivity (1 = healthy)
- `ml_dependency_health{dependency="redis"}` — Redis connectivity (1 = healthy)

**Example graph URL** (replace `$INSTANCE_IP`):
```
http://$INSTANCE_IP:30900/graph?g0.expr=up{job="ml-pipeline-api-service"}&g0.range_input=2h
```

## Troubleshooting

*   **Connection Refused**: Ensure the security group allows traffic on ports 30300-30900 from your IP.
*   **Model Not Updating**: 
    *   Check API logs: `ssh -i ml-pipeline-debug.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl logs -l app=ml-pipeline-api -n ml-pipeline --tail 50"`
    *   Check MLflow logs: `ssh -i ml-pipeline-debug.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl logs -l app=mlflow -n ml-pipeline --tail 50"`
    *   Ensure the model was actually promoted to "Production" in the MLflow UI.

## Cleanup

### Reset MLflow (Re-run Demo)

To reset the model registry and re-run the v1 vs v2 demo without destroying the cluster:

```bash
export MLFLOW_TRACKING_URI="http://$INSTANCE_IP:30500"
python scripts/demo/utilities/cleanup_models.py --all --force
```

This deletes all registered models and experiments from MLflow. The API will temporarily have no model to serve, then auto-loads the new one within 10 seconds after you re-train and promote v1.

> **Important:** After cleanup, you must restore the soft-deleted experiment before retraining:
> ```bash
> python -c "
> import mlflow
> mlflow.set_tracking_uri('$MLFLOW_TRACKING_URI')
> client = mlflow.MlflowClient()
> for exp in client.search_experiments(view_type=mlflow.entities.ViewType.DELETED_ONLY):
>     client.restore_experiment(exp.experiment_id)
>     print(f'Restored: {exp.name}')
> "
> ```
> MLflow's `delete_experiment` is a soft-delete — the experiment stays in "deleted" state and blocks re-creation with the same name. Restoring it makes it usable again.

### Destroy Infrastructure & Secrets

To stop all costs, simply destroy the Terraform infrastructure. This will automatically delete the EC2 instance and **permanently delete** the secrets from AWS Secrets Manager (recovery window is set to 0 days).

```bash
cd ops/terraform/aws/demo;
terraform destroy -auto-approve
```

> **Note**: You do not need to manually delete secrets using the script. Terraform manages their lifecycle.

## Cheatsheet

Quick reference for common commands. All assume `$INSTANCE_IP` and env vars are set (see step 2).

### SSH & Cluster

```bash
# SSH into the instance
ssh -i ml-pipeline-debug.pem ubuntu@$INSTANCE_IP

# List all pods
ssh -i ml-pipeline-debug.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl get pods -n ml-pipeline"

# Pod logs (replace <pod-name>)
ssh -i ml-pipeline-debug.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl logs <pod-name> -n ml-pipeline --tail 100"

# Logs by label
ssh -i ml-pipeline-debug.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl logs -l app=ml-pipeline-api -n ml-pipeline --tail 50"
ssh -i ml-pipeline-debug.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl logs -l app=mlflow -n ml-pipeline --tail 50"

# Training job logs
ssh -i ml-pipeline-debug.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl logs job/model-training -n ml-pipeline -c train"

# Evaluation job logs
ssh -i ml-pipeline-debug.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl logs job/model-evaluation -n ml-pipeline"

# Restart a deployment (e.g. after config change)
ssh -i ml-pipeline-debug.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl rollout restart deployment/ml-pipeline-api -n ml-pipeline"

# Delete completed/failed jobs
ssh -i ml-pipeline-debug.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl delete job model-training model-evaluation -n ml-pipeline --ignore-not-found"

# Re-apply kustomize manifests
ssh -i ml-pipeline-debug.pem ubuntu@$INSTANCE_IP "cd /opt/ml-platform && sudo k3s kubectl kustomize ops/k8s/overlays/aws-demo --load-restrictor LoadRestrictionsNone | sudo k3s kubectl apply -f -"
```

### MLflow & Models

```bash
# List registered models, versions, and experiments
export MLFLOW_TRACKING_URI="http://$INSTANCE_IP:30500"
python scripts/demo/utilities/list_models.py

# Compare models and find the best across experiments
python scripts/demo/utilities/compare_models.py

# Clean up all models and experiments (reset for re-demo)
python scripts/demo/utilities/cleanup_models.py --all --force

# Restore soft-deleted experiments (required after cleanup before retraining)
python -c "
import mlflow
mlflow.set_tracking_uri('$MLFLOW_TRACKING_URI')
client = mlflow.MlflowClient()
for exp in client.search_experiments(view_type=mlflow.entities.ViewType.DELETED_ONLY):
    client.restore_experiment(exp.experiment_id)
    print(f'Restored: {exp.name}')
"
```

### Training

```bash
export EC2_IP=$INSTANCE_IP

# Train with defaults (100 estimators)
./scripts/demo/demo-aws/trigger-training.sh

# Train weak baseline (for v1 demo)
./scripts/demo/demo-aws/trigger-training.sh --n-estimators 10 --max-depth 1 --auto-promote

# Train improved model (for v2 demo)
./scripts/demo/demo-aws/trigger-training.sh --n-estimators 200

# Train with class weighting (better fraud recall)
./scripts/demo/demo-aws/trigger-training.sh --n-estimators 200 --class-weight balanced
```

### API

```bash
export API_URL="http://${INSTANCE_IP}:30800"

# Health check
curl -s "$API_URL/health" | python -m json.tool

# Prediction request
curl -s -X POST "$API_URL/predict" \
  -H "Content-Type: application/json" \
  -d @data/sample/demo/requests/baseline_prediction_request.json | python -m json.tool

# API docs (open in browser)
echo "$API_URL/docs"
```

### S3 Data

```bash
# Upload training data
aws s3 cp data/sample/demo/datasets/fraud_detection.csv \
  s3://rt-ml-platform-training-data-demo/datasets/fraud_detection.csv

# List uploaded data
aws s3 ls s3://rt-ml-platform-training-data-demo/datasets/
```

---

## Automated Deployment (CD Pipeline)

When code is merged to `main`, the CD pipeline automatically:
1. Builds and pushes new Docker images to GHCR (tagged with the commit SHA).
2. SSHes into the EC2 instance and runs `kubectl set image` to update deployments.
3. K3s pulls the new images from GHCR and performs a **zero-downtime rolling update** (new pod starts → health check passes → old pod terminates).

This requires:
- **`ENABLE_DEMO_DEPLOY`** repo variable set to `true` (GitHub → Settings → Variables → Actions).
- **`EC2_SSH_KEY`** repo secret containing the SSH private key for the EC2 instance.

---

## Architecture Decisions

This section explains the rationale behind the technology choices for the AWS demo, and why certain managed services are intentionally not used.

### Why EC2 + K3s instead of EKS

| | EC2 + K3s (Current) | EKS Lite | EKS Production |
|---|---|---|---|
| **Monthly Cost** | ~$30 | ~$164 | ~$473 |
| **Control Plane** | K3s self-managed | AWS-managed, HA | AWS-managed, HA |
| **Nodes** | 1x t3.medium | 2x t3.medium Spot | 3x m5.large |

The EKS control plane alone costs $73/month with no application running. For a single-node demo workload, EC2 + K3s provides the same Kubernetes API surface at a fraction of the cost.

**Migration readiness:** The K8s manifests use Kustomize base + overlay structure (`ops/k8s/base/`, `ops/k8s/overlays/`). Migrating to EKS requires a new overlay (`ops/k8s/overlays/eks-demo/`) and Terraform modules for VPC/EKS/RDS — the application code and base manifests remain unchanged. See `local/next_steps/ec2-to-eks-migration.md` for the full phased migration plan.

### Why No Apache Beam Ingestion Pipeline in the Demo

Apache Beam pipelines are implemented in `src/feature_engineering/` and tested via the `--profile beam` Docker Compose profile in the local demo (`scripts/demo/demo-local/demo-local.sh`).

The AWS demo focuses on the **training-to-serving loop**: `[S3] -> [K8s Training Job] -> [MLflow] -> [Evaluation Gate] -> [API Auto-Promotion]`. Adding Beam to this demo would require standing up a streaming source (Kafka cluster or Kinesis stream), increasing infrastructure complexity and cost without demonstrating additional ML pipeline value.

### Why K8s Jobs for Training instead of SageMaker Training

Training runs as K8s Jobs inside the same K3s cluster as the serving API. This keeps the entire pipeline within one infrastructure boundary — no cross-VPC networking, no additional AWS service costs, and the same Job YAML runs identically on K3s, EKS, GKE, or any conformant Kubernetes cluster.

SageMaker Training is the planned next step for when training datasets grow beyond what a t3.medium can handle, or when GPU instances are needed. The migration path involves creating a `submit_job.py` script using the SageMaker Python SDK while keeping MLflow as the experiment tracker. See `local/next_steps/aws-training-migration.md` for the implementation plan.
