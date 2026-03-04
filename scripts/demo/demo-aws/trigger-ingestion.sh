#!/usr/bin/env bash
# =============================================================================
# Trigger Kinesis Data Ingestion Pipeline on AWS Demo Instance
# =============================================================================
# Runs the Kinesis producer -> Apache Beam feature engineering pipeline.
# Producer publishes N events to Kinesis; Beam reads and writes features to S3.
#
# The script applies the K8s Job manifests, waits for the producer to finish,
# then launches the Beam job and exits. Monitor the Beam pod separately:
#   kubectl get pods -n ml-pipeline -w
#   kubectl logs job/beam-ingestion -n ml-pipeline -f
#
# Usage:
#   ./trigger-ingestion.sh                       # defaults: 100 events
#   ./trigger-ingestion.sh --total-events 500    # custom event count
#   ./trigger-ingestion.sh --events-per-second 10
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
NAMESPACE="ml-pipeline"
TOTAL_EVENTS=100
EVENTS_PER_SECOND=5.0
OUTPUT_PREFIX="features"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
MANIFESTS_DIR="$PROJECT_ROOT/ops/k8s/overlays/aws-demo"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --total-events)      TOTAL_EVENTS="$2"; shift 2 ;;
    --events-per-second) EVENTS_PER_SECOND="$2"; shift 2 ;;
    --output-prefix)     OUTPUT_PREFIX="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--total-events N] [--events-per-second N] [--output-prefix PREFIX]"
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

# Helper: run SSH commands on the instance
remote() {
  ssh -o StrictHostKeyChecking=no ubuntu@"$EC2_IP" "$@"
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
echo "[1/3] Cleaning up previous jobs..."
remote "sudo k3s kubectl delete job kinesis-producer beam-ingestion -n $NAMESPACE --ignore-not-found=true"

# ---------------------------------------------------------------------------
# Step 2: Run Kinesis producer (wait for completion)
# ---------------------------------------------------------------------------
echo ""
echo "[2/3] Running Kinesis producer ($TOTAL_EVENTS events at ${EVENTS_PER_SECOND}/s)..."

# Patch the manifest with CLI overrides and apply via stdin
sed \
  -e "s|value: \"5.0\"|value: \"${EVENTS_PER_SECOND}\"|" \
  -e "s|value: \"100\"|value: \"${TOTAL_EVENTS}\"|" \
  "$MANIFESTS_DIR/job-kinesis-producer.yaml" \
  | ssh -o StrictHostKeyChecking=no ubuntu@"$EC2_IP" "sudo k3s kubectl apply -f -"

echo "  Waiting for producer to complete..."
if ! remote "sudo k3s kubectl wait --for=condition=complete job/kinesis-producer -n $NAMESPACE --timeout=300s"; then
  echo "ERROR: Kinesis producer job failed."
  remote "sudo k3s kubectl logs job/kinesis-producer -n $NAMESPACE --tail=20"
  exit 1
fi

echo "  Producer logs:"
remote "sudo k3s kubectl logs job/kinesis-producer -n $NAMESPACE" | tail -5

# ---------------------------------------------------------------------------
# Step 3: Launch Beam ingestion (fire and forget)
# ---------------------------------------------------------------------------
echo ""
echo "[3/3] Launching Apache Beam feature engineering pipeline..."

sed \
  -e "s|--output-prefix=features|--output-prefix=${OUTPUT_PREFIX}|" \
  "$MANIFESTS_DIR/job-beam-ingestion.yaml" \
  | ssh -o StrictHostKeyChecking=no ubuntu@"$EC2_IP" "sudo k3s kubectl apply -f -"

echo ""
echo "============================================"
echo "  Beam job submitted. Monitor with:"
echo "============================================"
echo ""
echo "  # Watch pod status:"
echo "  ssh ubuntu@$EC2_IP \"sudo k3s kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=beam-ingestion -w\""
echo ""
echo "  # Stream logs:"
echo "  ssh ubuntu@$EC2_IP \"sudo k3s kubectl logs job/beam-ingestion -n $NAMESPACE -f\""
echo ""
echo "  # Verify S3 output:"
echo "  aws s3 ls s3://${BUCKET}/${OUTPUT_PREFIX}/ --recursive"
echo ""
echo "  # Dashboards:"
echo "  MLflow:   http://$EC2_IP:30500"
echo "  API:      http://$EC2_IP:30800/docs"
echo "  Grafana:  http://$EC2_IP:30300"
echo "============================================"
