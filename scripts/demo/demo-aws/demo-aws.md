# AWS Cloud Demo Guide

This guide details how to run the End-to-End ML Platform demo against a live AWS EC2 instance. 
Unlike the local demo which runs everything on your machine, this workflow runs the **training and validaton** scripts locally on your laptop, but they communicate with the **remote infrastructure** (MLflow, Redis, API) deployed on AWS.

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
    --output text)
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
ssh -i ml-pipeline-debug.pem ubuntu@$INSTANCE_IP "sudo cat /var/log/user-data.log"
```

**Re-run Bootstrap (if needed):**
If the setup failed or you need to re-trigger the script:
```bash
ssh -i ml-pipeline-debug.pem ubuntu@$INSTANCE_IP "sudo /var/lib/cloud/instance/scripts/part-001"
```

> **Note:** You no longer need to manually pull/import Docker images. K3s pulls images directly from GHCR using an `imagePullSecret` configured during bootstrap.

**Verify Services:**
Once the script completes, ensure the platform pods are running:
```bash
ssh -i ml-pipeline-debug.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl get pods -n ml-pipeline"
```
*   You should see `ml-pipeline-api` and `ml-pipeline-mlflow` with status `Running`.

### 4. Train Model Version 1 (Baseline)

Run the training script locally. It will:
1.  Train a Random Forest model on your machine.
2.  Upload the model artifacts to the **remote** MLflow server (backed by S3/MinIO).
3.  Register the model as `fraud_detector` (Version 1).
4.  Promote it to "Production".

```bash
python scripts/demo/demo-aws/train.py
```

**What to expect:**
*   The script should output `Model logged with run_id: ...`
*   It automatically attempts to verify the API using the `$Env:API_URL` you set.

### 5. Verify API Prediction (Version 1)

Manually send a prediction request to the remote API to confirm it is serving Version 1.

```bash
curl -X POST "$API_URL/predict" \
  -H "Content-Type: application/json" \
  -d @data/sample/demo/requests/baseline_prediction_request.json
```

*   **Success Criteria**: Response contains `"model_version": "1"`.

### 6. Train & Upgrade Model (Version 2)

Simulate a model improvement cycle by training with different hyperparameters (e.g., more trees).

```bash
python scripts/demo/demo-aws/train.py --n-estimators 200
```

1.  Trains a new model (Version 2).
2.  Logs/Registers it to remote MLflow.
3.  Promotes Version 2 to "Production".

### 7. Verify Auto-Promotion (Zero-Downtime Deployment)

The remote API polls MLflow every **60 seconds** for changes to the "Production" alias. 

Wait ~60 seconds, then check the model version again:

```bash
curl -X POST "$API_URL/predict" \
  -H "Content-Type: application/json" \
  -d @data/sample/demo/requests/improved_prediction_request.json
```

*   **Success Criteria**: Response usually switches from `"model_version": "1"` to `"model_version": "2"` without any downtime.

---

## Accessing Dashboards

You can monitor the platform status via these URLs (replace hardcoded IPs with the dynamic IP):

| Service | Port | Description |
| :--- | :--- | :--- |
| **MLflow UI** | `30500` | http://$INSTANCE_IP:30500 |
| **Grafana** | `30300` | http://$INSTANCE_IP:30300 |
| **Prometheus**| `30900` | http://$INSTANCE_IP:30900 |
| **API Docs** | `30800` | http://$INSTANCE_IP:30800/docs |

## Troubleshooting

*   **Connection Refused**: Ensure the security group allows traffic on ports 30300-30900 from your IP.
*   **Model Not Updating**: 
    *   Check API logs: `ssh -i ml-pipeline-debug.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl logs -l app=ml-pipeline-api -n ml-pipeline --tail 50"`
    *   Check MLflow logs: `ssh -i ml-pipeline-debug.pem ubuntu@$INSTANCE_IP "sudo k3s kubectl logs -l app=mlflow -n ml-pipeline --tail 50"`
    *   Ensure the model was actually promoted to "Production" in the MLflow UI.

## Cleanup

### Destroy Infrastructure & Secrets

To stop all costs, simply destroy the Terraform infrastructure. This will automatically delete the EC2 instance and **permanently delete** the secrets from AWS Secrets Manager (recovery window is set to 0 days).

```bash
cd ops/terraform/aws/demo;
terraform destroy -auto-approve
```

> **Note**: You do not need to manually delete secrets using the script. Terraform manages their lifecycle.

## Automated Deployment (CD Pipeline)

When code is merged to `main`, the CD pipeline automatically:
1. Builds and pushes new Docker images to GHCR (tagged with the commit SHA).
2. SSHes into the EC2 instance and runs `kubectl set image` to update deployments.
3. K3s pulls the new images from GHCR and performs a **zero-downtime rolling update** (new pod starts → health check passes → old pod terminates).

This requires:
- **`ENABLE_DEMO_DEPLOY`** repo variable set to `true` (GitHub → Settings → Variables → Actions).
- **`EC2_SSH_KEY`** repo secret containing the SSH private key for the EC2 instance.
