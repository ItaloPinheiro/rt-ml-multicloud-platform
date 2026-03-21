#!/usr/bin/env bash
# =============================================================================
# Reset AWS Demo — Full Clean Slate
# =============================================================================
# Wipes all state (K8s jobs, MLflow, Feature Store, S3) so the demo can be
# rerun from scratch without destroying the cluster.
#
# Usage:
#   ./reset-demo.sh
#   ./reset-demo.sh --ssh-key ~/.ssh/my-key.pem
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
S3_BUCKET="rt-ml-platform-training-data-demo"
SSH_KEY="${SSH_KEY:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --ssh-key) SSH_KEY="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--ssh-key PATH]"
      echo "  Wipes all demo state (jobs, MLflow, Feature Store, S3) for a clean rerun."
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

# Verify SSH connectivity
echo "Verifying SSH connectivity to $INSTANCE_IP..."
if ! remote "echo ok" >/dev/null 2>&1; then
  echo "ERROR: Cannot SSH into ubuntu@$INSTANCE_IP"
  echo "  Key: $SSH_KEY"
  echo "  Check that the instance is running and the key is correct."
  exit 1
fi

# Read stream name and region from K8s ConfigMap
STREAM_NAME=$(remote "sudo k3s kubectl get configmap ml-pipeline-config -n $NAMESPACE -o jsonpath='{.data.KINESIS_STREAM_NAME}'" 2>/dev/null || echo "")
REGION=$(remote "sudo k3s kubectl get configmap ml-pipeline-config -n $NAMESPACE -o jsonpath='{.data.AWS_DEFAULT_REGION}'" 2>/dev/null || echo "us-east-1")

echo "============================================"
echo "  Reset Demo - Full Clean Slate"
echo "============================================"
echo "  Instance:  $INSTANCE_IP"
echo "  S3 bucket: $S3_BUCKET"
echo "  Stream:    ${STREAM_NAME:-not found}"
echo "  Region:    $REGION"
echo "============================================"
echo

# ---------------------------------------------------------------------------
# 1. Delete all K8s Jobs
# ---------------------------------------------------------------------------
echo "[1/5] Deleting all K8s Jobs..."
remote "sudo k3s kubectl delete jobs --all -n $NAMESPACE --ignore-not-found" 2>&1 || true
echo "  Done."
echo

# ---------------------------------------------------------------------------
# 2. Recreate Kinesis stream (purge old events)
# ---------------------------------------------------------------------------
if [ -n "$STREAM_NAME" ]; then
  echo "[2/5] Recreating Kinesis stream (purging retained events)..."
  # Delete the stream
  aws kinesis delete-stream --stream-name "$STREAM_NAME" --region "$REGION" 2>&1 || true
  echo "  Waiting for stream deletion..."
  aws kinesis wait stream-not-exists --stream-name "$STREAM_NAME" --region "$REGION" 2>&1 || true

  # Recreate with same config (1 shard, 24h retention)
  aws kinesis create-stream --stream-name "$STREAM_NAME" --shard-count 1 --region "$REGION" 2>&1
  echo "  Waiting for stream to become active..."
  aws kinesis wait stream-exists --stream-name "$STREAM_NAME" --region "$REGION" 2>&1
  echo "  Stream recreated."
else
  echo "[2/5] Skipping Kinesis reset (stream name not found in ConfigMap)."
fi
echo

# ---------------------------------------------------------------------------
# 3. Clean up MLflow (models + experiments, auto-restores for reuse)
# ---------------------------------------------------------------------------
echo "[3/5] Cleaning up MLflow (models + experiments)..."
export MLFLOW_TRACKING_URI="http://$INSTANCE_IP:30500"
cd "$PROJECT_ROOT"
python scripts/demo/utilities/cleanup_models.py --all --force
echo

# ---------------------------------------------------------------------------
# 4. Flush Feature Store (Redis + PostgreSQL)
# ---------------------------------------------------------------------------
echo "[4/5] Flushing Feature Store..."

# Redis (requires auth)
REDIS_PASS=$(remote \
  "sudo k3s kubectl get secret ml-pipeline-secrets -n $NAMESPACE -o jsonpath='{.data.REDIS_PASSWORD}' | base64 -d")
remote "sudo k3s kubectl exec deployment/redis -n $NAMESPACE -- redis-cli -a $REDIS_PASS FLUSHALL" 2>&1 | grep -v "Warning: Using a password"
echo "  Redis flushed."

# PostgreSQL
remote "sudo k3s kubectl exec deployment/postgres -n $NAMESPACE -- \
  psql -U mlflow -d mlflow -c 'TRUNCATE feature_store, prediction_logs CASCADE'" 2>&1
echo "  PostgreSQL tables truncated."
echo

# ---------------------------------------------------------------------------
# 5. Clear S3 data
# ---------------------------------------------------------------------------
echo "[5/5] Clearing S3 data..."
aws s3 rm "s3://$S3_BUCKET/features/" --recursive --quiet 2>&1 || true
aws s3 rm "s3://$S3_BUCKET/datasets/" --recursive --quiet 2>&1 || true
echo "  S3 cleared."
echo

echo "============================================"
echo "  Demo reset complete!"
echo "============================================"
echo
echo "  Next step: rerun the pipeline from step 4:"
echo "    ./scripts/demo/demo-aws/trigger-ingestion.sh --total-events 100"
echo "============================================"
