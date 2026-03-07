#!/usr/bin/env bash
# =============================================================================
# Trigger Training Pipeline on AWS Demo Instance
# =============================================================================
# Runs the full training -> evaluation -> promotion pipeline on the K3s cluster.
# Job manifests live in ops/k8s/overlays/aws-demo/ and are patched at apply time
# with CLI overrides (n-estimators, experiment, etc.).
#
# Prerequisites:
#   - EC2 instance running with K3s and aws-demo overlay applied
#   - SSH key at ~/.ssh/rt-ml-platform-aws-ec2.pem (or set SSH_KEY)
#   - Training data uploaded to S3 (run trigger-ingestion.sh first)
#
# Usage:
#   ./trigger-training.sh                              # defaults
#   ./trigger-training.sh --n-estimators 200
#   ./trigger-training.sh --auto-promote
#   ./trigger-training.sh --ssh-key ~/.ssh/other.pem
#
# Environment variables:
#   INSTANCE_IP       - Skip auto-discovery, connect to this IP
#   SSH_KEY           - Path to SSH private key (default: ~/.ssh/rt-ml-platform-aws-ec2.pem)
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
NAMESPACE="ml-pipeline"
N_ESTIMATORS=100
EXPERIMENT="fraud_detection"
AUTO_PROMOTE=false
CLASS_WEIGHT=""
MAX_DEPTH=""
SSH_KEY="${SSH_KEY:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
MANIFESTS_DIR="$PROJECT_ROOT/ops/k8s/overlays/aws-demo"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --n-estimators) N_ESTIMATORS="$2"; shift 2 ;;
    --experiment)   EXPERIMENT="$2"; shift 2 ;;
    --auto-promote) AUTO_PROMOTE=true; shift ;;
    --class-weight) CLASS_WEIGHT="$2"; shift 2 ;;
    --max-depth)    MAX_DEPTH="$2"; shift 2 ;;
    --ssh-key)      SSH_KEY="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--n-estimators N] [--max-depth N] [--class-weight balanced] [--experiment NAME] [--auto-promote] [--ssh-key PATH]"
      echo "  SSH key: set SSH_KEY env var or use --ssh-key (default: ~/.ssh/rt-ml-platform-aws-ec2.pem)"
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# SSH Configuration
# ---------------------------------------------------------------------------
SSH_KEY="${SSH_KEY:-$HOME/.ssh/rt-ml-platform-aws-ec2.pem}"

if [ ! -f "$SSH_KEY" ]; then
  echo "ERROR: SSH key not found at $SSH_KEY"
  echo "  Place your EC2 key at ~/.ssh/rt-ml-platform-aws-ec2.pem"
  echo "  or set SSH_KEY / use --ssh-key to the correct path."
  exit 1
fi

SSH_OPTS=(-i "$SSH_KEY" -o StrictHostKeyChecking=no)

# Get instance IP
if [ -z "${INSTANCE_IP:-}" ]; then
  echo "Discovering EC2 instance IP..."
  INSTANCE_IP=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=rt-ml-platform-demo-instance" \
              "Name=instance-state-name,Values=running" \
    --query "Reservations[*].Instances[*].PublicIpAddress" \
    --output text)

  if [ -z "$INSTANCE_IP" ]; then
    echo "ERROR: No running demo instance found"
    exit 1
  fi
fi

# Helper: run SSH commands on the instance
remote() {
  ssh "${SSH_OPTS[@]}" ubuntu@"$INSTANCE_IP" "$@"
}

# Verify SSH connectivity before proceeding
echo "Verifying SSH connectivity to $INSTANCE_IP..."
if ! remote "echo ok" >/dev/null 2>&1; then
  echo "ERROR: Cannot SSH into ubuntu@$INSTANCE_IP"
  echo "  Key: $SSH_KEY"
  echo "  Check that the instance is running and the key is correct."
  exit 1
fi

echo "============================================"
echo "  Training Pipeline - AWS Demo"
echo "============================================"
echo "  Instance:     $INSTANCE_IP"
echo "  SSH key:      $SSH_KEY"
echo "  Estimators:   $N_ESTIMATORS"
echo "  Class weight: ${CLASS_WEIGHT:-none}"
echo "  Max depth:    ${MAX_DEPTH:-unlimited}"
echo "  Experiment:   $EXPERIMENT"
echo "  Auto-promote: $AUTO_PROMOTE"
echo "============================================"

# Build training args for sed patching
# Base manifest has: "--n-estimators=100" and "--experiment=fraud_detection"
TRAIN_SED_ARGS=()
TRAIN_SED_ARGS+=(-e "s|--n-estimators=100|--n-estimators=${N_ESTIMATORS}|")
TRAIN_SED_ARGS+=(-e "s|--experiment=fraud_detection|--experiment=${EXPERIMENT}|")

# Add optional args by appending to the args list
EXTRA_ARGS=""
if [ "$AUTO_PROMOTE" = "true" ]; then
  EXTRA_ARGS="${EXTRA_ARGS}\n        - \"--auto-promote\""
fi
if [ -n "$CLASS_WEIGHT" ]; then
  EXTRA_ARGS="${EXTRA_ARGS}\n        - \"--class-weight=${CLASS_WEIGHT}\""
fi
if [ -n "$MAX_DEPTH" ]; then
  EXTRA_ARGS="${EXTRA_ARGS}\n        - \"--max-depth=${MAX_DEPTH}\""
fi

# If we have extra args, insert them after the last training arg line
if [ -n "$EXTRA_ARGS" ]; then
  TRAIN_SED_ARGS+=(-e "s|--model-name=fraud_detector\"|--model-name=fraud_detector\"${EXTRA_ARGS}|")
fi

# ---------------------------------------------------------------------------
# Step 1: Clean up previous jobs
# ---------------------------------------------------------------------------
echo ""
echo "[1/3] Cleaning up previous jobs..."
remote "sudo k3s kubectl delete job model-training model-evaluation -n $NAMESPACE --ignore-not-found=true"

# ---------------------------------------------------------------------------
# Step 2: Run Training Job
# ---------------------------------------------------------------------------
echo ""
echo "[2/3] Running training job ($N_ESTIMATORS estimators)..."

sed "${TRAIN_SED_ARGS[@]}" "$MANIFESTS_DIR/job-model-training.yaml" \
  | ssh "${SSH_OPTS[@]}" ubuntu@"$INSTANCE_IP" "sudo k3s kubectl apply -f -"

echo "  Waiting for training to complete..."
if ! remote "sudo k3s kubectl wait --for=condition=complete job/model-training -n $NAMESPACE --timeout=600s"; then
  echo "ERROR: Training job failed."
  remote "sudo k3s kubectl logs job/model-training -n $NAMESPACE -c train --tail=20"
  exit 1
fi

echo "  Training logs:"
remote "sudo k3s kubectl logs job/model-training -n $NAMESPACE -c train" | tail -10

# ---------------------------------------------------------------------------
# Step 3: Run Evaluation Gate (unless auto-promote)
# ---------------------------------------------------------------------------
if [ "$AUTO_PROMOTE" = "true" ]; then
  echo ""
  echo "[3/3] Skipped evaluation gate (--auto-promote)"
else
  echo ""
  echo "[3/3] Running evaluation gate..."

  cat "$MANIFESTS_DIR/job-model-evaluation.yaml" \
    | ssh "${SSH_OPTS[@]}" ubuntu@"$INSTANCE_IP" "sudo k3s kubectl apply -f -"

  echo "  Waiting for evaluation..."
  if ! remote "sudo k3s kubectl wait --for=condition=complete job/model-evaluation -n $NAMESPACE --timeout=120s"; then
    echo "  Evaluation result: REJECTED"
    remote "sudo k3s kubectl logs job/model-evaluation -n $NAMESPACE"
    exit 1
  fi

  echo "  Evaluation logs:"
  remote "sudo k3s kubectl logs job/model-evaluation -n $NAMESPACE" | tail -10
fi

# ---------------------------------------------------------------------------
# Verify API picked up the model
# ---------------------------------------------------------------------------
echo ""
echo "Verifying API model update..."

API_URL="http://$INSTANCE_IP:30800"
echo "  Waiting for API auto-update cycle (up to 30s)..."

for i in $(seq 1 6); do
  RESPONSE=$(curl -s "$API_URL/health" || echo "{}")
  echo "  Attempt $i/6: $RESPONSE"
  if echo "$RESPONSE" | grep -q '"status":"healthy"'; then
    echo ""
    echo "============================================"
    echo "  Training pipeline complete!"
    echo "============================================"
    echo "  MLflow:  http://$INSTANCE_IP:30500"
    echo "  API:     http://$INSTANCE_IP:30800/docs"
    echo "  Grafana: http://$INSTANCE_IP:30300"
    echo "============================================"
    exit 0
  fi
  sleep 5
done

echo "  WARNING: API health check did not confirm healthy status"
exit 0
