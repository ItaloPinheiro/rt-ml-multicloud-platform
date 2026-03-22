# AWS Cloud Demo Guide

End-to-End ML Platform demo on a live AWS EC2 instance. The full pipeline: **stream ingestion → feature engineering → Feature Store → materialization → model training → evaluation → serving with real-time feature lookup**.

All orchestration scripts run from your laptop and execute K8s Jobs on the remote cluster via SSH.

> **Target Environment**: AWS EC2 Instance (Ubuntu + K3s)

## Prerequisites

*   **Python 3.13+** installed locally.
*   **Bash** (recommended) or Git Bash on Windows.
*   **AWS CLI** installed and configured.
*   Project dependencies installed (`pip install -r requirements.txt` or `poetry install`).
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

Verify IP was found
```bash
if [ -z "$INSTANCE_IP" ]; then echo "Error: Instance not found or not running!"; else echo "Instance IP: $INSTANCE_IP"; fi
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
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP "sudo cat /var/log/user-data.log"
```

**Re-run Bootstrap (if needed):**
If the setup failed or you need to re-trigger the script:
```bash
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP "sudo /var/lib/cloud/instance/scripts/part-001"
```

> **Note:** You no longer need to manually pull/import Docker images. K3s pulls images directly from GHCR using an `imagePullSecret` configured during bootstrap.

**Verify Services:**
Once the script completes, ensure the platform pods are running:
```bash
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl get pods -n ml-pipeline"
```
```bash
ssh -t -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP "watch -n 5 'sudo k3s kubectl get pods -n ml-pipeline'"
```

*   You should see `ml-pipeline-api` and `ml-pipeline-mlflow` with status `Running`.

### 4. Run Feature Engineering Pipeline (Kinesis + Beam)

Generate deterministic demo events and publish them to Kinesis, then run the Apache Beam pipeline to extract features and store them in the Feature Store (Redis + PostgreSQL).

```bash
# Generate the deterministic demo events (500 curated transactions, ~15% fraud)
python scripts/demo/demo-aws/generate_demo_events.py

# Run the full ingestion pipeline with the pre-generated events
./scripts/demo/demo-aws/trigger-ingestion.sh --events-file data/sample/demo/events/demo_events.jsonl
```

**What happens:**
1. The events file is uploaded to S3 and the Kinesis producer Job publishes all 500 events to the `rt-ml-platform-demo-kds-stream`.
2. An Apache Beam Job (DirectRunner) reads all events from the stream using `TRIM_HORIZON`.
3. Features are extracted, validated, windowed (60s fixed), and aggregated by `user_id`.
4. Features are written to the Feature Store (Redis for hot cache, PostgreSQL for cold storage).

> **Why deterministic events?** Random data produces inconsistent fraud rates across runs, which can cause v2 to fail at detecting fraud in the demo. The curated dataset has a controlled ~15% fraud rate with clear patterns (night + high-risk merchant + high amount) that v1 reliably misses and v2 reliably catches.

**Options:**
- `--events-file PATH` — use pre-generated JSONL events instead of random (recommended for demos)
- `--total-events N` — number of random events to produce (default: 100, ignored with `--events-file`)
- `--events-per-second N` — publishing rate (default: batch mode)

> See `docs/pipeline/kds-apache-beam-deployment.md` for full architecture details and production deployment guidance.

### 5. Inspect Feature Store

Verify that the Feature Store was populated by the Beam pipeline.

**Via API:**

```bash
# List feature groups and entity counts
curl -s "$API_URL/features/groups" | python -m json.tool

# Feature group statistics (column names, row counts)
curl -s "$API_URL/features/stats/transaction_features" | python -m json.tool
curl -s "$API_URL/features/stats/aggregated_features" | python -m json.tool
```

**Via PostgreSQL (direct database query):**

```bash
# Feature groups summary (groups, unique entities, total rows)
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP \
  "sudo k3s kubectl exec deployment/postgres -n ml-pipeline -- psql -U mlflow -d mlflow -c \
  \"SELECT feature_group, COUNT(DISTINCT entity_id) AS entities, COUNT(*) AS rows FROM feature_store GROUP BY feature_group\""

# Sample entity from transaction_features (pretty-printed JSONB)
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP \
  "sudo k3s kubectl exec deployment/postgres -n ml-pipeline -- psql -U mlflow -d mlflow -c \
  \"SELECT entity_id, jsonb_pretty(features) FROM feature_store WHERE feature_group = 'transaction_features' LIMIT 1\""

# Transaction features: extract key columns as a readable table
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP \
  "sudo k3s kubectl exec deployment/postgres -n ml-pipeline -- psql -U mlflow -d mlflow -c \
  \"SELECT entity_id,
    features->>'merchant_category' AS merchant,
    features->>'amount' AS amount,
    features->>'hour_of_day' AS hour,
    features->>'day_of_week' AS dow,
    features->>'is_weekend' AS weekend,
    features->>'payment_method' AS payment,
    features->>'risk_score' AS risk
  FROM feature_store
  WHERE feature_group = 'transaction_features'
  LIMIT 10\""

# Check aggregated_features (record_count, avg_amount per user)
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP \
  "sudo k3s kubectl exec deployment/postgres -n ml-pipeline -- psql -U mlflow -d mlflow -c \
  \"SELECT entity_id, jsonb_pretty(features) FROM feature_store WHERE feature_group = 'aggregated_features' LIMIT 1\""
```

*   **Success Criteria**: Feature group `transaction_features` appears with entities populated. `aggregated_features` contains per-user aggregates (record_count, avg_amount).

**Pick an entity ID** from the Feature Store output for use in the prediction steps:
```bash
ENTITY_ID=$(ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP \
  "sudo k3s kubectl exec deployment/postgres -n ml-pipeline -- psql -U mlflow -d mlflow -t -A -c 'SELECT entity_id FROM feature_store LIMIT 1'")
echo "Using entity: $ENTITY_ID"

curl -s "$API_URL/features/$ENTITY_ID" | python -m json.tool
```

### 6. Train Model Version 1 (Baseline)

Training runs as **K8s Jobs inside the cluster**. With `--use-feature-store`, the script first materializes Feature Store data to a Parquet file on S3, then runs the training Job which downloads and trains from that Parquet file.

We start with a **weak baseline** model: few estimators and shallow trees (max depth 1). This model will have decent accuracy (~80%) but poor fraud detection (f1 near 0) because the shallow trees can't learn complex fraud patterns.

```bash
./scripts/demo/demo-aws/trigger-training.sh --use-feature-store --n-estimators 10 --max-depth 1 --auto-promote
```

> We use `--auto-promote` for v1 since there is no champion to compare against yet.

**What happens:**
1. **Materialization Job** reads from the Feature Store and writes `fraud_detection.parquet` to S3.
2. **Training Job** init container downloads the Parquet file from S3, then trains a RandomForest model.
3. Model v1 is registered in MLflow and auto-promoted (no prior champion).
4. API auto-detects the new production model within 10 seconds.

### 7. Verify API Prediction (Version 1 — Weak Baseline)

The API can now serve predictions by looking up features directly from the Feature Store using an `entity_id`:

```bash
curl -s -X POST "$API_URL/predict" \
  -H "Content-Type: application/json" \
  -d "{\"entity_id\": \"$ENTITY_ID\"}" | python -m json.tool
```

*   **Success Criteria**: Response contains `"model_version": "1"` and `"features_used"` shows the features fetched from the Feature Store.

**Test both scenarios** — v1 is a weak model (10 trees, max depth 1), so it predicts **both cases as not-fraud**. This is intentional — it demonstrates why a better model is needed:

**Legitimate transaction** (grocery, business hours, low amount — expect `prediction: 0`):
```bash
curl -s -X POST "$API_URL/predict" \
  -H "Content-Type: application/json" \
  -d @data/sample/demo/requests/legitimate_transaction.json | python -m json.tool
```

**Fraudulent transaction** (cash advance, 3 AM weekend, high amount — also `prediction: 0` with v1):
```bash
curl -s -X POST "$API_URL/predict" \
  -H "Content-Type: application/json" \
  -d @data/sample/demo/requests/fraud_transaction.json | python -m json.tool
```

> **Key insight:** v1 classifies **everything as not-fraud** (prediction: 0). The shallow trees (depth 1) cannot learn complex fraud patterns — they achieve ~80-90% accuracy simply by predicting the majority class. This is why the f1_score for fraud is near 0. The upgrade to v2 fixes this.

### 8. Train & Upgrade Model (Version 2 — Improved)

Now train a **stronger model** with more estimators, controlled depth, and balanced class weighting:

```bash
./scripts/demo/demo-aws/trigger-training.sh --use-feature-store --n-estimators 200 --max-depth 5 --class-weight balanced
```

**What happens:**
1.  Materialization runs again (picks up any new features since v1).
2.  Training Job runs with 200 estimators, max depth 5, and `class_weight=balanced` (vs 10 trees at depth 1 with no weighting in v1).
3.  Evaluation gate compares v2 against v1 champion on **accuracy** and **f1_score**.
4.  v2 will have better accuracy and much better fraud recall, so it gets promoted.

> **Why `--class-weight balanced`?** Fraud is rare (~5-10% of transactions). Without class weighting, the model optimizes for overall accuracy by predicting the majority class (not-fraud). `balanced` tells the classifier to weight fraud samples inversely proportional to their frequency, producing stronger fraud recall -- exactly what you'd want in production for imbalanced classification.

> **Why `--max-depth 5`?** Unlimited depth causes the trees to memorize exact training patterns (overfitting). When new inputs arrive that don't follow the exact same feature paths, the model outputs near-50% probabilities even for clear fraud cases. Limiting depth to 5 forces the trees to learn general decision rules, producing confident predictions (~86% for fraud, ~96% for legitimate) on new inputs.

> **How the evaluation gate decides:** The challenger must meet a minimum accuracy threshold (0.80) AND beat the champion on both accuracy and f1_score. See `src/models/evaluation/evaluate_and_promote.py` for details.

### 9. Verify Auto-Promotion (Zero-Downtime Deployment)

The API polls MLflow every **10 seconds** for changes to the "production" alias. After v2 is promoted, re-run the **exact same predictions** to demonstrate the improvement.

```bash
curl -s -X POST "$API_URL/predict" \
  -H "Content-Type: application/json" \
  -d "{\"entity_id\": \"$ENTITY_ID\"}" | python -m json.tool
```

*   **Success Criteria**: Response now contains `"model_version": "2"` — the API picked up the new model automatically, zero downtime.

**Re-run the same payloads** from step 7 to demonstrate v2's improved fraud detection:

**Legitimate transaction** (grocery, business hours, low amount — still `prediction: 0`, same as v1):
```bash
curl -s -X POST "$API_URL/predict" \
  -H "Content-Type: application/json" \
  -d @data/sample/demo/requests/legitimate_transaction.json | python -m json.tool
```

**Fraudulent transaction** (cash advance, 3 AM weekend, high amount — now `prediction: 1`, v2 catches the fraud that v1 missed):
```bash
curl -s -X POST "$API_URL/predict" \
  -H "Content-Type: application/json" \
  -d @data/sample/demo/requests/fraud_transaction.json | python -m json.tool
```

> **Key insight:** Same API, same payloads, better results. v2 (200 trees, max depth 5, balanced class weight) correctly flags the fraudulent transaction with ~86% confidence that v1 (10 trees, depth 1, no weighting) missed entirely. The legitimate transaction remains correctly classified at ~96% confidence. This is the zero-downtime model upgrade in action — the evaluation gate verified v2 beats v1 on both accuracy and f1_score before promoting it.

### End-to-End Pipeline Architecture

```
[Kinesis Stream]
       |
       v
[Beam Feature Engineering]  (extract, validate, window, aggregate)
       |
       v
[Feature Store (Redis + PostgreSQL)]
       |
       +--> [Materialization Job] --> [Parquet on S3]
       |                                     |
       |                              [Init Container: download]
       |                                     |
       |                              [Training Job: train model]
       |                                     |
       |                              [Register in MLflow]
       |                                     |
       |                              [Evaluation Gate: compare vs champion]
       |                                     |
       |                              [Promote if better]
       |                                     |
       +--> [API: predict by entity_id] <----+  (auto-detects new model)
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

> **Note:** If you see "Failed to load chart data" on the GenAI Overview page, this is because the GenAI-specific database tables have no data for traditional ML experiments. Switch to the "Model training" tab. If errors persist on the Model training tab, run `mlflow db upgrade <backend-store-uri>` against the PostgreSQL instance to apply any pending schema migrations.

### Grafana

Access Grafana at `http://$INSTANCE_IP:30300`.

- **Default credentials**: `admin` / `admin` (you will be prompted to change on first login)
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
    *   Check API logs: `ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl logs -l app=ml-pipeline-api -n ml-pipeline --tail 50"`
    *   Check MLflow logs: `ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl logs -l app=mlflow -n ml-pipeline --tail 50"`
    *   Ensure the model was actually promoted to "Production" in the MLflow UI.

## Cleanup

### Reset Demo (Full Clean Slate)

To wipe all state and rerun the demo from scratch without destroying the cluster:

```bash
./scripts/demo/demo-aws/reset-demo.sh
```

This deletes all K8s Jobs, clears MLflow (models + experiments), flushes the Feature Store (Redis + PostgreSQL), and removes S3 data.

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
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP

# List all pods
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl get pods -n ml-pipeline"

# Pod logs (replace <pod-name>)
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl logs <pod-name> -n ml-pipeline --tail 100"

# Logs by label
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl logs -l app=ml-pipeline-api -n ml-pipeline --tail 50"
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl logs -l app=mlflow -n ml-pipeline --tail 50"

# Training job logs
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl logs job/model-training -n ml-pipeline -c train"

# Evaluation job logs
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl logs job/model-evaluation -n ml-pipeline"

# Kinesis producer job logs
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl logs job/kinesis-producer -n ml-pipeline"

# Beam ingestion job logs
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl logs job/beam-ingestion -n ml-pipeline"

# Materialization job logs
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl logs job/materialize-training -n ml-pipeline -c materialize"

# Restart a deployment (e.g. after config change)
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl rollout restart deployment/ml-pipeline-api -n ml-pipeline"

# Delete completed/failed jobs
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl delete job materialize-training model-training model-evaluation -n ml-pipeline --ignore-not-found"

# Re-apply kustomize manifests
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP "cd /opt/ml-platform && sudo k3s kubectl kustomize ops/k8s/overlays/aws-demo --load-restrictor LoadRestrictionsNone | sudo k3s kubectl apply -f -"
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
# Train from Feature Store (materialize → Parquet → train)
./scripts/demo/demo-aws/trigger-training.sh --use-feature-store --n-estimators 10 --max-depth 1 --auto-promote

# Train v2 from Feature Store (with balanced class weighting and controlled depth for fraud recall)
./scripts/demo/demo-aws/trigger-training.sh --use-feature-store --n-estimators 200 --max-depth 5 --class-weight balanced

# Train from pre-uploaded S3 CSV (legacy, no materialization)
./scripts/demo/demo-aws/trigger-training.sh --n-estimators 100 --auto-promote
```

### Ingestion (Kinesis + Beam)

```bash
# Generate deterministic demo events (recommended for reproducible demos)
python scripts/demo/demo-aws/generate_demo_events.py

# Run ingestion with deterministic events
./scripts/demo/demo-aws/trigger-ingestion.sh --events-file data/sample/demo/events/demo_events.jsonl

# Run ingestion with random events (100 by default)
./scripts/demo/demo-aws/trigger-ingestion.sh

# Run with more random events at higher rate
./scripts/demo/demo-aws/trigger-ingestion.sh --total-events 500 --events-per-second 10

# Verify S3 output
aws s3 ls s3://rt-ml-platform-training-data-demo/features/ --recursive

# Clean up ingestion jobs
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl delete job kinesis-producer beam-ingestion -n ml-pipeline --ignore-not-found"
```

### API

```bash
# Health check
curl -s "$API_URL/health" | python -m json.tool

# Predict by entity_id (Feature Store lookup)
curl -s -X POST "$API_URL/predict" \
  -H "Content-Type: application/json" \
  -d "{\"entity_id\": \"$ENTITY_ID\"}" | python -m json.tool

# Predict with explicit features — legitimate transaction (expect not-fraud)
curl -s -X POST "$API_URL/predict" \
  -H "Content-Type: application/json" \
  -d @data/sample/demo/requests/legitimate_transaction.json | python -m json.tool

# Predict with explicit features — fraud transaction (expect fraud)
curl -s -X POST "$API_URL/predict" \
  -H "Content-Type: application/json" \
  -d @data/sample/demo/requests/fraud_transaction.json | python -m json.tool

# API docs (open in browser)
echo "$API_URL/docs"
```

### Feature Store

```bash
# List feature groups (API)
curl -s "$API_URL/features/groups" | python -m json.tool

# Feature group statistics (API)
curl -s "$API_URL/features/stats/transaction_features" | python -m json.tool

# Entity features (API)
curl -s "$API_URL/features/$ENTITY_ID" | python -m json.tool

# Inspect via CLI (detailed output)
python scripts/demo/utilities/list_features.py --summary --redis-host $INSTANCE_IP --db-host $INSTANCE_IP
python scripts/demo/utilities/list_features.py --groups --redis-host $INSTANCE_IP --db-host $INSTANCE_IP
python scripts/demo/utilities/list_features.py --features $ENTITY_ID transaction_features --redis-host $INSTANCE_IP --db-host $INSTANCE_IP
python scripts/demo/utilities/list_features.py --stats transaction_features --redis-host $INSTANCE_IP --db-host $INSTANCE_IP

# Materialization job logs (runs automatically via --use-feature-store)
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP \
  "sudo k3s kubectl logs job/materialize-training -n ml-pipeline"

# Clean up all pipeline jobs
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP \
  "sudo k3s kubectl delete job materialize-training model-training model-evaluation -n ml-pipeline --ignore-not-found"
```

### PostgreSQL (Database Inspection)

```bash
# List all tables in the database
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP \
  "sudo k3s kubectl exec deployment/postgres -n ml-pipeline -- psql -U mlflow -d mlflow -c '\dt'"

# Check Feature Store table schema
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP \
  "sudo k3s kubectl exec deployment/postgres -n ml-pipeline -- psql -U mlflow -d mlflow -c '\d feature_store'"

# Check ML experiments table schema
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP \
  "sudo k3s kubectl exec deployment/postgres -n ml-pipeline -- psql -U mlflow -d mlflow -c '\d ml_experiments'"

# Count rows in Feature Store
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP \
  "sudo k3s kubectl exec deployment/postgres -n ml-pipeline -- psql -U mlflow -d mlflow -c 'SELECT count(*) FROM feature_store'"

# List feature groups and entity counts
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP \
  "sudo k3s kubectl exec deployment/postgres -n ml-pipeline -- psql -U mlflow -d mlflow -c 'SELECT feature_group, count(DISTINCT entity_id) AS entities, count(*) AS rows FROM feature_store GROUP BY feature_group'"

# Check prediction logs
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP \
  "sudo k3s kubectl exec deployment/postgres -n ml-pipeline -- psql -U mlflow -d mlflow -c 'SELECT count(*) FROM prediction_logs'"

# List MLflow experiments (MLflow-owned table)
ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem ubuntu@$INSTANCE_IP \
  "sudo k3s kubectl exec deployment/postgres -n ml-pipeline -- psql -U mlflow -d mlflow -c 'SELECT experiment_id, name, lifecycle_stage FROM experiments'"
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

### Why Self-Hosted MLflow instead of SageMaker

The platform is designed to be **cloud-agnostic**, ingesting from Kafka, Kinesis, and Pub/Sub. MLflow is open-source and portable across any infrastructure — the same tracking server runs on local Docker Compose, K3s on EC2, or EKS.

SageMaker Model Registry ties the model lifecycle to AWS, creating vendor lock-in across experiment tracking, model versioning, and serving endpoints. By self-hosting MLflow, the model registry API (`mlflow.MlflowClient`), alias-based promotion (`production` alias), and artifact storage are all portable.

**Future plan:** SageMaker Training Jobs are planned for compute-only (offloading heavy training to managed GPU instances), while experiment tracking and model registry remain on MLflow. See `local/next_steps/aws-training-migration.md`.

### Why DirectRunner for Apache Beam (Not FlinkRunner)

The Beam feature engineering pipeline runs as a K8s Job using `DirectRunner` on the single t3.large EC2 instance. This avoids standing up a dedicated Apache Flink cluster for the demo, keeping infrastructure minimal. The `DirectRunner` processes events in-process using multi-threading, which is sufficient for the bounded demo workload (100-500 events).

For production, the same pipeline code switches to `FlinkRunner` targeting AWS Managed Service for Apache Flink — no code changes required, only the `--runner` flag changes. See `docs/pipeline/kds-apache-beam-deployment.md` for the production deployment path.

### Why K8s Jobs for Training instead of SageMaker Training

Training runs as K8s Jobs inside the same K3s cluster as the serving API. This keeps the entire pipeline within one infrastructure boundary — no cross-VPC networking, no additional AWS service costs, and the same Job YAML runs identically on K3s, EKS, GKE, or any conformant Kubernetes cluster.

SageMaker Training is the planned next step for when training datasets grow beyond what a t3.medium can handle, or when GPU instances are needed. The migration path involves creating a `submit_job.py` script using the SageMaker Python SDK while keeping MLflow as the experiment tracker. See `local/next_steps/aws-training-migration.md` for the implementation plan.
