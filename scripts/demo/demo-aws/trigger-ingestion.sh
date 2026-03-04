#!/usr/bin/env bash
# =============================================================================
# Trigger Kinesis Data Ingestion Pipeline on AWS Demo Instance
# =============================================================================
# Runs the Kinesis producer -> Apache Beam feature engineering pipeline.
# Producer publishes N events to Kinesis; Beam reads and writes features to S3.
#
# Prerequisites:
#   - EC2 instance running with K3s
#   - SSH key configured
#   - Kinesis stream provisioned (via Terraform)
#   - Beam image available in GHCR
#
# Usage:
#   ./trigger-ingestion.sh                       # defaults: 100 events
#   ./trigger-ingestion.sh --total-events 500    # custom event count
#   ./trigger-ingestion.sh --events-per-second 10 # faster publishing
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
NAMESPACE="ml-pipeline"
TOTAL_EVENTS=100
EVENTS_PER_SECOND=5.0
OUTPUT_PREFIX="features"
BEAM_IMAGE="ghcr.io/italopinheiro/rt-ml-multicloud-platform/beam:main"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --total-events)      TOTAL_EVENTS="$2"; shift 2 ;;
    --events-per-second) EVENTS_PER_SECOND="$2"; shift 2 ;;
    --output-prefix)     OUTPUT_PREFIX="$2"; shift 2 ;;
    --beam-image)        BEAM_IMAGE="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--total-events N] [--events-per-second N] [--output-prefix PREFIX] [--beam-image IMAGE]"
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

# Read config values from the cluster
STREAM_NAME=$(ssh -o StrictHostKeyChecking=no ubuntu@"$EC2_IP" \
  "sudo k3s kubectl get configmap ml-pipeline-config -n $NAMESPACE -o jsonpath='{.data.KINESIS_STREAM_NAME}' 2>/dev/null" || echo "")
BUCKET=$(ssh ubuntu@"$EC2_IP" \
  "sudo k3s kubectl get configmap ml-pipeline-config -n $NAMESPACE -o jsonpath='{.data.TRAINING_DATA_BUCKET}' 2>/dev/null" || echo "")
REGION=$(ssh ubuntu@"$EC2_IP" \
  "sudo k3s kubectl get configmap ml-pipeline-config -n $NAMESPACE -o jsonpath='{.data.AWS_DEFAULT_REGION}' 2>/dev/null" || echo "us-east-1")

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
echo "  Beam image:   $BEAM_IMAGE"
echo "============================================"

# ---------------------------------------------------------------------------
# Step 1: Clean up previous jobs
# ---------------------------------------------------------------------------
echo ""
echo "[1/4] Cleaning up previous jobs..."
ssh ubuntu@"$EC2_IP" \
  "sudo k3s kubectl delete job kinesis-producer beam-ingestion -n $NAMESPACE --ignore-not-found=true"

# ---------------------------------------------------------------------------
# Step 2: Run Kinesis producer
# ---------------------------------------------------------------------------
echo ""
echo "[2/4] Running Kinesis producer ($TOTAL_EVENTS events at ${EVENTS_PER_SECOND}/s)..."

ssh ubuntu@"$EC2_IP" "cat <<'JOBEOF' | sudo k3s kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: kinesis-producer
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/name: kinesis-producer
    app.kubernetes.io/component: ingestion
    app.kubernetes.io/part-of: ml-pipeline-platform
spec:
  backoffLimit: 1
  activeDeadlineSeconds: 300
  ttlSecondsAfterFinished: 3600
  template:
    metadata:
      labels:
        app.kubernetes.io/name: kinesis-producer
        app.kubernetes.io/component: ingestion
    spec:
      restartPolicy: Never
      imagePullSecrets:
      - name: ghcr-pull-secret
      containers:
      - name: producer
        image: $BEAM_IMAGE
        imagePullPolicy: Always
        command: [\"python\", \"/app/scripts/data_generation/publish_kinesis_events.py\"]
        args:
        - \"--stream-name=$STREAM_NAME\"
        - \"--region=$REGION\"
        - \"--events-per-second=$EVENTS_PER_SECOND\"
        - \"--total-events=$TOTAL_EVENTS\"
        env:
        - name: PYTHONPATH
          value: \"/app\"
        resources:
          requests:
            memory: \"128Mi\"
            cpu: \"100m\"
          limits:
            memory: \"256Mi\"
            cpu: \"250m\"
JOBEOF"

echo "  Waiting for producer to complete..."
if ! ssh ubuntu@"$EC2_IP" \
  "sudo k3s kubectl wait --for=condition=complete job/kinesis-producer -n $NAMESPACE --timeout=300s"; then
  echo "ERROR: Kinesis producer job failed."
  ssh ubuntu@"$EC2_IP" "sudo k3s kubectl logs job/kinesis-producer -n $NAMESPACE" | tail -20
  exit 1
fi

echo "  Producer logs:"
ssh ubuntu@"$EC2_IP" \
  "sudo k3s kubectl logs job/kinesis-producer -n $NAMESPACE" | tail -5

# ---------------------------------------------------------------------------
# Step 3: Run Beam ingestion pipeline
# ---------------------------------------------------------------------------
echo ""
echo "[3/4] Running Apache Beam feature engineering pipeline..."

ssh ubuntu@"$EC2_IP" "cat <<'JOBEOF' | sudo k3s kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: beam-ingestion
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/name: beam-ingestion
    app.kubernetes.io/component: ingestion
    app.kubernetes.io/part-of: ml-pipeline-platform
spec:
  backoffLimit: 1
  activeDeadlineSeconds: 600
  ttlSecondsAfterFinished: 3600
  template:
    metadata:
      labels:
        app.kubernetes.io/name: beam-ingestion
        app.kubernetes.io/component: ingestion
    spec:
      restartPolicy: Never
      imagePullSecrets:
      - name: ghcr-pull-secret
      containers:
      - name: beam-runner
        image: $BEAM_IMAGE
        imagePullPolicy: Always
        command: [\"python\", \"/app/scripts/demo/demo-aws/ingest_kinesis_s3.py\"]
        args:
        - \"--stream-name=$STREAM_NAME\"
        - \"--s3-bucket=$BUCKET\"
        - \"--region=$REGION\"
        - \"--output-prefix=$OUTPUT_PREFIX\"
        - \"--runner=DirectRunner\"
        - \"--initial-position=TRIM_HORIZON\"
        env:
        - name: PYTHONPATH
          value: \"/app\"
        resources:
          requests:
            memory: \"512Mi\"
            cpu: \"500m\"
          limits:
            memory: \"1Gi\"
            cpu: \"1000m\"
JOBEOF"

echo "  Waiting for Beam pipeline to complete (or fail)..."
BEAM_TIMEOUT=600
BEAM_ELAPSED=0
BEAM_STATUS=""
while [ $BEAM_ELAPSED -lt $BEAM_TIMEOUT ]; do
  # Check for completion or failure via jsonpath on job conditions
  BEAM_STATUS=$(ssh ubuntu@"$EC2_IP" \
    "sudo k3s kubectl get job beam-ingestion -n $NAMESPACE -o jsonpath='{.status.conditions[0].type}' 2>/dev/null" || echo "")

  if [ "$BEAM_STATUS" = "Complete" ]; then
    echo "  Beam pipeline completed successfully."
    break
  elif [ "$BEAM_STATUS" = "Failed" ]; then
    echo "  ERROR: Beam pipeline job failed!"
    echo ""
    echo "  Beam pipeline logs:"
    ssh ubuntu@"$EC2_IP" "sudo k3s kubectl logs job/beam-ingestion -n $NAMESPACE --tail=30"
    exit 1
  fi

  sleep 5
  BEAM_ELAPSED=$((BEAM_ELAPSED + 5))
done

if [ "$BEAM_STATUS" != "Complete" ]; then
  echo "  ERROR: Beam pipeline timed out after ${BEAM_TIMEOUT}s"
  ssh ubuntu@"$EC2_IP" "sudo k3s kubectl logs job/beam-ingestion -n $NAMESPACE --tail=30"
  exit 1
fi

echo "  Beam pipeline logs:"
ssh ubuntu@"$EC2_IP" \
  "sudo k3s kubectl logs job/beam-ingestion -n $NAMESPACE" | tail -10

# ---------------------------------------------------------------------------
# Step 4: Verify S3 output
# ---------------------------------------------------------------------------
echo ""
echo "[4/4] Verifying S3 features output..."
S3_OUTPUT=$(aws s3 ls "s3://${BUCKET}/${OUTPUT_PREFIX}/" --recursive 2>&1 || echo "")

if [ -n "$S3_OUTPUT" ]; then
  echo "  Features written to S3:"
  echo "$S3_OUTPUT" | head -20
else
  echo "  WARNING: No output found at s3://${BUCKET}/${OUTPUT_PREFIX}/"
  echo "  Check Beam pipeline logs for errors."
fi

echo ""
echo "============================================"
echo "  Ingestion pipeline complete!"
echo "============================================"
echo "  Features at: s3://${BUCKET}/${OUTPUT_PREFIX}/"
echo "  MLflow:      http://$EC2_IP:30500"
echo "  API:         http://$EC2_IP:30800/docs"
echo "  Grafana:     http://$EC2_IP:30300"
echo "============================================"
