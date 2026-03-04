#!/usr/bin/env bash
# =============================================================================
# Trigger Kinesis Data Ingestion Pipeline on AWS Demo Instance
# =============================================================================
# Runs the full Kinesis producer -> Beam feature engineering -> training data
# assembly pipeline. Producer publishes N events to Kinesis; Beam extracts
# features to S3; the assembler joins features and writes a training CSV.
#
# Usage:
#   ./trigger-ingestion.sh                       # defaults: 100 events
#   ./trigger-ingestion.sh --total-events 500    # custom event count
#   ./trigger-ingestion.sh --events-per-second 10
#   ./trigger-ingestion.sh --ssh-key ~/.ssh/my-key.pem
#
# Environment variables:
#   EC2_IP       - Skip auto-discovery, connect to this IP
#   SSH_KEY      - Path to SSH private key (or use --ssh-key)
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
NAMESPACE="ml-pipeline"
TOTAL_EVENTS=100
EVENTS_PER_SECOND=5.0
OUTPUT_PREFIX="features"
SSH_KEY="${SSH_KEY:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
MANIFESTS_DIR="$PROJECT_ROOT/ops/k8s/overlays/aws-demo"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --total-events)      TOTAL_EVENTS="$2"; shift 2 ;;
    --events-per-second) EVENTS_PER_SECOND="$2"; shift 2 ;;
    --output-prefix)     OUTPUT_PREFIX="$2"; shift 2 ;;
    --ssh-key)           SSH_KEY="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--total-events N] [--events-per-second N] [--output-prefix PREFIX] [--ssh-key PATH]"
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

# Build SSH options (key is optional — uses ssh-agent or default key if not set)
SSH_OPTS=(-o StrictHostKeyChecking=no)
if [ -n "$SSH_KEY" ]; then
  SSH_OPTS+=(-i "$SSH_KEY")
fi

# Helper: run SSH commands on the instance
remote() {
  ssh "${SSH_OPTS[@]}" ubuntu@"$EC2_IP" "$@"
}

# Read config values from the cluster
STREAM_NAME=$(remote "sudo k3s kubectl get configmap ml-pipeline-config -n $NAMESPACE -o jsonpath='{.data.KINESIS_STREAM_NAME}'" 2>/dev/null || echo "")
BUCKET=$(remote "sudo k3s kubectl get configmap ml-pipeline-config -n $NAMESPACE -o jsonpath='{.data.TRAINING_DATA_BUCKET}'" 2>/dev/null || echo "")
REGION=$(remote "sudo k3s kubectl get configmap ml-pipeline-config -n $NAMESPACE -o jsonpath='{.data.AWS_DEFAULT_REGION}'" 2>/dev/null || echo "us-east-1")

if [ -z "$STREAM_NAME" ]; then
  echo "ERROR: KINESIS_STREAM_NAME not set in ConfigMap. Did you apply the aws-demo overlay?"
  exit 1
fi
if [ -z "$BUCKET" ]; then
  echo "ERROR: TRAINING_DATA_BUCKET not set in ConfigMap."
  exit 1
fi

echo "============================================"
echo "  Ingestion Pipeline - AWS Demo"
echo "============================================"
echo "  Instance:     $EC2_IP"
echo "  Stream:       $STREAM_NAME"
echo "  S3 bucket:    $BUCKET"
echo "  Region:       $REGION"
echo "  Events:       $TOTAL_EVENTS at ${EVENTS_PER_SECOND}/s"
echo "  Output:       s3://${BUCKET}/${OUTPUT_PREFIX}"
echo "============================================"

# ---------------------------------------------------------------------------
# Step 1: Clean up previous jobs
# ---------------------------------------------------------------------------
echo ""
echo "[1/5] Cleaning up previous jobs..."
remote "sudo k3s kubectl delete job kinesis-producer beam-ingestion assemble-training-data -n $NAMESPACE --ignore-not-found=true"

# ---------------------------------------------------------------------------
# Step 2: Run Kinesis producer (wait for completion)
# ---------------------------------------------------------------------------
echo ""
echo "[2/5] Running Kinesis producer ($TOTAL_EVENTS events at ${EVENTS_PER_SECOND}/s)..."

# Patch the manifest with CLI overrides and apply via stdin
sed \
  -e "s|value: \"5.0\"|value: \"${EVENTS_PER_SECOND}\"|" \
  -e "s|value: \"100\"|value: \"${TOTAL_EVENTS}\"|" \
  "$MANIFESTS_DIR/job-kinesis-producer.yaml" \
  | ssh "${SSH_OPTS[@]}" ubuntu@"$EC2_IP" "sudo k3s kubectl apply -f -"

echo "  Waiting for producer to complete..."
if ! remote "sudo k3s kubectl wait --for=condition=complete job/kinesis-producer -n $NAMESPACE --timeout=300s"; then
  echo "ERROR: Kinesis producer job failed."
  remote "sudo k3s kubectl logs job/kinesis-producer -n $NAMESPACE --tail=20"
  exit 1
fi

echo "  Producer logs:"
remote "sudo k3s kubectl logs job/kinesis-producer -n $NAMESPACE" | tail -5

# ---------------------------------------------------------------------------
# Step 3: Run Beam ingestion (wait for completion)
# ---------------------------------------------------------------------------
echo ""
echo "[3/5] Running Apache Beam feature engineering pipeline..."

sed \
  -e "s|--output-prefix=features|--output-prefix=${OUTPUT_PREFIX}|" \
  "$MANIFESTS_DIR/job-beam-ingestion.yaml" \
  | ssh "${SSH_OPTS[@]}" ubuntu@"$EC2_IP" "sudo k3s kubectl apply -f -"

echo "  Waiting for Beam pipeline to complete..."
if ! remote "sudo k3s kubectl wait --for=condition=complete job/beam-ingestion -n $NAMESPACE --timeout=600s"; then
  echo "ERROR: Beam ingestion job failed."
  remote "sudo k3s kubectl logs job/beam-ingestion -n $NAMESPACE --tail=20"
  exit 1
fi

echo "  Beam logs (tail):"
remote "sudo k3s kubectl logs job/beam-ingestion -n $NAMESPACE" | tail -5

# ---------------------------------------------------------------------------
# Step 4: Assemble training data from Beam features
# ---------------------------------------------------------------------------
echo ""
echo "[4/5] Assembling training data from Beam features..."

cat "$MANIFESTS_DIR/job-assemble-training-data.yaml" \
  | ssh "${SSH_OPTS[@]}" ubuntu@"$EC2_IP" "sudo k3s kubectl apply -f -"

echo "  Waiting for assembly to complete..."
if ! remote "sudo k3s kubectl wait --for=condition=complete job/assemble-training-data -n $NAMESPACE --timeout=300s"; then
  echo "ERROR: Training data assembly failed."
  remote "sudo k3s kubectl logs job/assemble-training-data -n $NAMESPACE --tail=20"
  exit 1
fi

echo "  Assembly logs:"
remote "sudo k3s kubectl logs job/assemble-training-data -n $NAMESPACE" | tail -10

# ---------------------------------------------------------------------------
# Step 5: Verify outputs
# ---------------------------------------------------------------------------
echo ""
echo "[5/5] Verifying outputs..."

echo "  Feature files in S3:"
aws s3 ls "s3://${BUCKET}/${OUTPUT_PREFIX}/" --recursive 2>/dev/null | head -5 || echo "  (could not list features)"

echo "  Training CSV:"
aws s3 ls "s3://${BUCKET}/datasets/fraud_detection.csv" 2>/dev/null || echo "  WARNING: fraud_detection.csv not found in S3"

echo ""
echo "============================================"
echo "  Ingestion pipeline complete!"
echo "============================================"
echo "  Features:  s3://${BUCKET}/${OUTPUT_PREFIX}/"
echo "  Training:  s3://${BUCKET}/datasets/fraud_detection.csv"
echo ""
echo "  Next step: run trigger-training.sh"
echo ""
echo "  Dashboards:"
echo "  MLflow:   http://$EC2_IP:30500"
echo "  API:      http://$EC2_IP:30800/docs"
echo "  Grafana:  http://$EC2_IP:30300"
echo "============================================"
