#!/usr/bin/env bash
# =============================================================================
# Trigger Training Pipeline on AWS Demo Instance
# =============================================================================
# Runs the full training -> evaluation -> promotion pipeline on the K3s cluster.
#
# Prerequisites:
#   - EC2 instance running with K3s
#   - SSH key configured
#   - Training data uploaded to S3 (or available in the image)
#
# Usage:
#   ./trigger-training.sh                    # defaults: 100 estimators
#   ./trigger-training.sh --n-estimators 200 # custom estimators
#   ./trigger-training.sh --auto-promote     # skip evaluation gate
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
NAMESPACE="ml-pipeline"
N_ESTIMATORS=100
EXPERIMENT="fraud_detection"
AUTO_PROMOTE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --n-estimators) N_ESTIMATORS="$2"; shift 2 ;;
    --experiment)   EXPERIMENT="$2"; shift 2 ;;
    --auto-promote) AUTO_PROMOTE=true; shift ;;
    -h|--help)
      echo "Usage: $0 [--n-estimators N] [--experiment NAME] [--auto-promote]"
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# Get EC2 IP
if [ -z "${EC2_IP:-}" ]; then
  echo "Discovering EC2 instance IP..."
  EC2_IP=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=rt-ml-platform-demo-instance" \
              "Name=instance-state-name,Values=running" \
    --query "Reservations[*].Instances[*].PublicIpAddress" \
    --output text)

  if [ -z "$EC2_IP" ]; then
    echo "ERROR: No running demo instance found"
    exit 1
  fi
fi

echo "============================================"
echo "  Training Pipeline - AWS Demo"
echo "============================================"
echo "  Instance:     $EC2_IP"
echo "  Estimators:   $N_ESTIMATORS"
echo "  Experiment:   $EXPERIMENT"
echo "  Auto-promote: $AUTO_PROMOTE"
echo "============================================"

# Build training args
TRAIN_ARGS="--data-path=/data/fraud_detection.csv"
TRAIN_ARGS="$TRAIN_ARGS --mlflow-uri=http://mlflow-service:5000"
TRAIN_ARGS="$TRAIN_ARGS --experiment=$EXPERIMENT"
TRAIN_ARGS="$TRAIN_ARGS --model-name=fraud_detector"
TRAIN_ARGS="$TRAIN_ARGS --n-estimators=$N_ESTIMATORS"
if [ "$AUTO_PROMOTE" = "true" ]; then
  TRAIN_ARGS="$TRAIN_ARGS --auto-promote"
fi

# ---------------------------------------------------------------------------
# Step 1: Run Training Job
# ---------------------------------------------------------------------------
echo ""
echo "[1/3] Submitting training job..."

# Get the current API image for consistency
API_IMAGE=$(ssh -o StrictHostKeyChecking=no ubuntu@"$EC2_IP" \
  "sudo k3s kubectl get deployment ml-pipeline-api -n $NAMESPACE -o jsonpath='{.spec.template.spec.containers[0].image}'")
echo "  Using image: $API_IMAGE"

# Get S3 bucket from configmap
BUCKET=$(ssh ubuntu@"$EC2_IP" \
  "sudo k3s kubectl get configmap ml-pipeline-config -n $NAMESPACE -o jsonpath='{.data.TRAINING_DATA_BUCKET}' 2>/dev/null" || echo "")

# Clean up previous jobs
ssh ubuntu@"$EC2_IP" \
  "sudo k3s kubectl delete job model-training -n $NAMESPACE --ignore-not-found=true"

# Create and apply training job
ssh ubuntu@"$EC2_IP" "cat <<'JOBEOF' | sudo k3s kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: model-training
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/name: model-training
    app.kubernetes.io/component: training
spec:
  backoffLimit: 2
  activeDeadlineSeconds: 600
  ttlSecondsAfterFinished: 3600
  template:
    spec:
      restartPolicy: Never
      initContainers:
      - name: download-data
        image: amazon/aws-cli:latest
        command: [\"sh\", \"-c\"]
        args:
        - |
          if [ -n \"$BUCKET\" ]; then
            echo \"Downloading from S3...\"
            aws s3 cp \"s3://${BUCKET}/datasets/fraud_detection.csv\" /data/fraud_detection.csv
          else
            echo \"ERROR: No S3 bucket configured (TRAINING_DATA_BUCKET not set)\"
            exit 1
          fi
        volumeMounts:
        - name: training-data
          mountPath: /data
        resources:
          requests:
            memory: \"64Mi\"
            cpu: \"50m\"
          limits:
            memory: \"128Mi\"
            cpu: \"100m\"
      containers:
      - name: train
        image: $API_IMAGE
        command: [\"python\", \"-m\", \"src.models.training.train\"]
        args: [\"--data-path=/data/fraud_detection.csv\", \"--mlflow-uri=http://mlflow-service:5000\", \"--experiment=$EXPERIMENT\", \"--model-name=fraud_detector\", \"--n-estimators=$N_ESTIMATORS\"]
        envFrom:
        - configMapRef:
            name: ml-pipeline-config
        - secretRef:
            name: ml-pipeline-secrets
        volumeMounts:
        - name: training-data
          mountPath: /data
        resources:
          requests:
            memory: \"1Gi\"
            cpu: \"500m\"
          limits:
            memory: \"2Gi\"
            cpu: \"1000m\"
      volumes:
      - name: training-data
        emptyDir: {}
JOBEOF"

echo "  Waiting for training to complete..."
ssh ubuntu@"$EC2_IP" \
  "sudo k3s kubectl wait --for=condition=complete job/model-training -n $NAMESPACE --timeout=600s"

echo "  Training logs:"
ssh ubuntu@"$EC2_IP" \
  "sudo k3s kubectl logs job/model-training -n $NAMESPACE -c train"

# ---------------------------------------------------------------------------
# Step 2: Run Evaluation Gate (unless auto-promote)
# ---------------------------------------------------------------------------
if [ "$AUTO_PROMOTE" = "true" ]; then
  echo ""
  echo "[2/3] Skipped evaluation gate (--auto-promote)"
else
  echo ""
  echo "[2/3] Running evaluation gate..."

  ssh ubuntu@"$EC2_IP" \
    "sudo k3s kubectl delete job model-evaluation -n $NAMESPACE --ignore-not-found=true"

  ssh ubuntu@"$EC2_IP" "cat <<'JOBEOF' | sudo k3s kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: model-evaluation
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/name: model-evaluation
    app.kubernetes.io/component: evaluation
spec:
  backoffLimit: 1
  activeDeadlineSeconds: 120
  ttlSecondsAfterFinished: 3600
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: evaluate
        image: $API_IMAGE
        command: [\"python\", \"-m\", \"src.models.evaluation.evaluate_and_promote\"]
        args: [\"--mlflow-uri=http://mlflow-service:5000\", \"--model-name=fraud_detector\", \"--min-accuracy=0.80\"]
        envFrom:
        - configMapRef:
            name: ml-pipeline-config
        - secretRef:
            name: ml-pipeline-secrets
        resources:
          requests:
            memory: \"512Mi\"
            cpu: \"250m\"
          limits:
            memory: \"1Gi\"
            cpu: \"500m\"
JOBEOF"

  echo "  Waiting for evaluation..."
  ssh ubuntu@"$EC2_IP" \
    "sudo k3s kubectl wait --for=condition=complete job/model-evaluation -n $NAMESPACE --timeout=120s" || {
    echo "  Evaluation result: REJECTED"
    ssh ubuntu@"$EC2_IP" "sudo k3s kubectl logs job/model-evaluation -n $NAMESPACE"
    exit 1
  }

  echo "  Evaluation logs:"
  ssh ubuntu@"$EC2_IP" \
    "sudo k3s kubectl logs job/model-evaluation -n $NAMESPACE"
fi

# ---------------------------------------------------------------------------
# Step 3: Verify API picked up the model
# ---------------------------------------------------------------------------
echo ""
echo "[3/3] Verifying API model update..."

API_URL="http://$EC2_IP:30800"
echo "  Waiting for API auto-update cycle (up to 30s)..."

for i in $(seq 1 6); do
  RESPONSE=$(curl -s "$API_URL/health" || echo "{}")
  echo "  Attempt $i/6: $RESPONSE"
  if echo "$RESPONSE" | grep -q '"status":"healthy"'; then
    echo ""
    echo "============================================"
    echo "  Training pipeline complete!"
    echo "============================================"
    echo "  MLflow:  http://$EC2_IP:30500"
    echo "  API:     http://$EC2_IP:30800/docs"
    echo "  Grafana: http://$EC2_IP:30300"
    echo "============================================"
    exit 0
  fi
  sleep 5
done

echo "  WARNING: API health check did not confirm healthy status"
exit 0
