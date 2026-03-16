# KDS + Apache Beam: Deployment and Operations Guide

## Overview

This document covers the end-to-end deployment of the Kinesis Data Streams (KDS) to S3 feature engineering pipeline using Apache Beam. It includes architecture details, infrastructure provisioning, K8s deployment, demo execution, and production scaling guidance.

For a quick-start on running the pipeline locally, see [apache-beam-kinesis-to-s3.md](apache-beam-kinesis-to-s3.md).

---

## Architecture

```
                          AWS Cloud
  ┌─────────────────────────────────────────────────────────┐
  │                                                         │
  │  ┌──────────────┐    ┌──────────────────────────────┐   │
  │  │   Kinesis     │    │  K3s Cluster (EC2 t3.large)  │   │
  │  │   Data        │    │                              │   │
  │  │   Stream      │───>│  ┌────────────────────────┐  │   │
  │  │ (1 shard,     │    │  │ Beam Job (DirectRunner) │  │   │
  │  │  PROVISIONED) │    │  │                        │  │   │
  │  └──────────────┘    │  │  ReadFromKinesis        │  │   │
  │                       │  │    │                    │  │   │
  │                       │  │  FeatureExtraction      │  │   │
  │                       │  │    │                    │  │   │
  │                       │  │  ValidateFeatures       │  │   │
  │                       │  │    │                    │  │   │
  │                       │  │  FixedWindows (60s)     │  │   │
  │                       │  │    │                    │  │   │
  │                       │  │  GroupBy(user_id)       │  │   │
  │                       │  │    │                    │  │   │
  │                       │  │  AggregateFeatures      │  │   │
  │                       │  │    │                    │  │   │
  │  ┌──────────────┐    │  │  WriteToText (S3)       │  │   │
  │  │     S3        │<───│  └────────────────────────┘  │   │
  │  │  Training     │    │                              │   │
  │  │  Data Bucket  │    │  ┌────────────────────────┐  │   │
  │  │              │    │  │ Producer Job           │  │   │
  │  │  /features/  │    │  │ publish_kinesis_events │──────>│ KDS
  │  │  /datasets/  │    │  └────────────────────────┘  │   │
  │  └──────────────┘    └──────────────────────────────┘   │
  └─────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Producer Job** publishes mock transaction events to KDS (partitioned by `user_id`)
2. **Beam Job** reads from KDS using `ReadFromKinesis` with `TRIM_HORIZON` position
3. **FeatureExtraction** (DoFn) parses JSON events and extracts 30+ features:
   - Transaction features: amount, log-transformed amount, amount category
   - Temporal features: hour, day-of-week, is_weekend, is_night, is_business_hours
   - Categorical features: location, device, channel, merchant
   - Numerical features: risk_score, fraud_score, credit_score, balance ratios
4. **ValidateFeatures** (DoFn) checks required fields, numeric ranges, categorical values
   - Valid records continue downstream; invalid records route to error stream
5. **Windowing** groups events into 60-second fixed windows
6. **AggregateFeatures** (DoFn) computes per-user aggregations:
   - Sum/mean/std/min/max/median of transaction amounts
   - Unique merchant/channel/payment-method counts
   - Weekend/night/business-hours transaction ratios
7. **WriteToText** writes JSON shards to S3: `features/` and `aggregated/` prefixes
8. **WriteToFeatureStore** (optional) writes features to the Feature Store via batched bulk upserts. Enabled by setting `output.type` to `feature_store` or `s3+feature_store` in pipeline config

### Error Routing

Failed transforms and invalid records are isolated into separate output streams rather than crashing the pipeline. The pipeline uses Beam's `TaggedOutput` for routing:
- `main` — valid features and aggregations
- `errors` — exceptions during processing
- `invalid` — records that fail validation rules

---

## Infrastructure

### Terraform Resources

All infrastructure is provisioned via `ops/terraform/aws/demo/`:

| Resource | File | Description |
|---|---|---|
| `aws_kinesis_stream.demo_stream` | `main.tf` | 1 shard, PROVISIONED mode, 24h retention |
| `aws_iam_policy.beam_pipeline_policy` | `iam.tf` | Kinesis read/write + S3 read/write |
| `aws_iam_role_policy_attachment.beam_pipeline_attach` | `iam.tf` | Attaches beam policy to EC2 role |
| S3 training data bucket | `bootstrap/main.tf` | `rt-ml-platform-training-data-demo` |

**IAM permissions granted to EC2 instance role:**
- Kinesis: `DescribeStream`, `GetRecords`, `GetShardIterator`, `ListShards`, `ListStreams`, `SubscribeToShard`, `PutRecord`, `PutRecords`
- S3: `PutObject`, `PutObjectAcl`, `GetObject`, `ListBucket`, `DeleteObject`

**IMDSv2 Configuration:**
The EC2 instance has `http_put_response_hop_limit = 2` (`main.tf` line 282), allowing K8s pods to reach the instance metadata service through the container network layer. This means pods inherit the EC2 instance role automatically via boto3's default credential chain — no explicit AWS credentials needed.

### Terraform Outputs

```bash
cd ops/terraform/aws/demo
terraform output kinesis_stream_name   # rt-ml-platform-demo-kds-stream
terraform output training_data_bucket  # rt-ml-platform-training-data-demo
```

---

## Kubernetes Deployment

### ConfigMap Keys

The following keys are added to the `ml-pipeline-config` ConfigMap:

| Key | Base Default | AWS Demo Override |
|---|---|---|
| `KINESIS_STREAM_NAME` | `""` | `rt-ml-platform-demo-kds-stream` |
| `AWS_DEFAULT_REGION` | `us-east-1` | `us-east-1` |
| `TRAINING_DATA_BUCKET` | `""` | `rt-ml-platform-training-data-demo` |

### Docker Image

The Beam runner image is built from `ops/docker/beam/Dockerfile`:
- Base: `python:3.13-slim`
- Includes: JRE (required for some Beam runners), `apache-beam[gcp,aws]`, `boto3`, `structlog`
- Contains: `src/`, `configs/`, `scripts/`
- Non-root user: `beam:beam`
- GHCR tag: `ghcr.io/<owner>/rt-ml-multicloud-platform/beam:main`

Built and pushed automatically by the CD pipeline (`.github/workflows/cd.yml`) on every merge to `main`.

### K8s Jobs

The pipeline runs as two sequential K8s Jobs (applied inline by `trigger-ingestion.sh`):

**kinesis-producer Job:**
- Image: beam GHCR image
- Command: `python /app/scripts/data_generation/publish_kinesis_events.py`
- Resources: 128Mi request / 256Mi limit
- Timeout: 300s
- Publishes N events then terminates

**beam-ingestion Job:**
- Image: beam GHCR image
- Command: `python -m src.feature_engineering.beam`
- Resources: 512Mi request / 1Gi limit
- Timeout: 600s
- Reads all events (TRIM_HORIZON), processes, writes to S3, then terminates

---

## Demo Walkthrough

### Prerequisites

1. Terraform infrastructure applied (`ops/terraform/aws/demo/`)
2. EC2 instance bootstrapped with K3s
3. Beam image available in GHCR (pushed by CD pipeline)
4. Training data uploaded to S3 (for subsequent training steps)

### Running the Ingestion Pipeline

```bash
# Set EC2 IP
export INSTANCE_IP=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=rt-ml-platform-demo-instance" \
            "Name=instance-state-name,Values=running" \
  --query "Reservations[*].Instances[*].PublicIpAddress" \
  --output text)

# Run with defaults (100 events at 5/s)
./scripts/demo/demo-aws/trigger-ingestion.sh

# Run with custom parameters
./scripts/demo/demo-aws/trigger-ingestion.sh --total-events 500 --events-per-second 10
```

### What Happens

1. Previous `kinesis-producer` and `beam-ingestion` Jobs are deleted
2. Producer Job publishes events to KDS (takes ~20s for 100 events at 5/s)
3. Beam Job reads all events from KDS, processes, and writes to S3 (takes ~30-60s)
4. S3 output is verified

### Verify Output

```bash
# List feature files in S3
aws s3 ls s3://rt-ml-platform-training-data-demo/features/ --recursive

# Check Job logs
ssh ubuntu@$INSTANCE_IP "sudo k3s kubectl logs job/kinesis-producer -n ml-pipeline"
ssh ubuntu@$INSTANCE_IP "sudo k3s kubectl logs job/beam-ingestion -n ml-pipeline"
```

### Full Demo Sequence (Ingestion + Training)

```bash
export INSTANCE_IP=$INSTANCE_IP

# Step 1: Upload training data
aws s3 cp data/sample/demo/datasets/fraud_detection.csv \
  s3://rt-ml-platform-training-data-demo/datasets/fraud_detection.csv

# Step 2: Run feature engineering pipeline
./scripts/demo/demo-aws/trigger-ingestion.sh --total-events 100

# Step 3: Train baseline model
./scripts/demo/demo-aws/trigger-training.sh --n-estimators 10 --max-depth 1 --auto-promote

# Step 4: Train improved model (evaluation gate compares against v1)
./scripts/demo/demo-aws/trigger-training.sh --n-estimators 200
```

---

## Local Development

### Running Locally with DirectRunner

The pipeline can run entirely on your local machine using the DirectRunner, connecting to real AWS services (Kinesis and S3).

**Install dependencies:**
```bash
poetry install --only main,processing
```

**Configure AWS credentials:**
```bash
export AWS_ACCESS_KEY_ID="your_access_key"
export AWS_SECRET_ACCESS_KEY="your_secret_key"
export AWS_DEFAULT_REGION="us-east-1"
```

**Start the data producer (terminal 1):**
```bash
poetry run python scripts/data_generation/publish_kinesis_events.py \
  --stream-name rt-ml-platform-demo-kds-stream \
  --events-per-second 2 \
  --total-events 50
```

**Run the pipeline (terminal 2):**
```bash
poetry run python -m src.feature_engineering.beam \
  --stream-name rt-ml-platform-demo-kds-stream \
  --s3-bucket rt-ml-platform-training-data-demo \
  --runner DirectRunner \
  --initial-position TRIM_HORIZON
```

### Programmatic Configuration

```python
from src.feature_engineering.beam.pipelines import (
    FeatureEngineeringPipeline,
    create_aws_pipeline_config,
)

config = create_aws_pipeline_config(
    stream_name="rt-ml-platform-demo-kds-stream",
    region="us-east-1",
    s3_bucket="rt-ml-platform-training-data-demo",
    output_prefix="features",
)

# Default runner is DirectRunner; override for production:
# config["runner"] = "FlinkRunner"

pipeline = FeatureEngineeringPipeline(config)
result = pipeline.run_streaming_pipeline()
result.wait_until_finish()
```

---

## Production Deployment

### FlinkRunner with AWS Managed Flink

For production workloads, switch to `FlinkRunner` targeting AWS Managed Service for Apache Flink. This provides:
- Horizontal auto-scaling based on throughput
- Checkpointing and exactly-once processing semantics
- Managed infrastructure (no cluster operations)

```bash
poetry run python -m src.feature_engineering.beam \
  --stream-name prod-ingestion-stream \
  --s3-bucket prod-ml-features \
  --runner FlinkRunner
```

### Scaling Considerations

| Parameter | Demo | Production |
|---|---|---|
| Runner | DirectRunner | FlinkRunner |
| KDS Shards | 1 (PROVISIONED) | N (ON_DEMAND or scaled PROVISIONED) |
| Workers | 2 threads | Auto-scaled parallelism |
| Window | 60s fixed | Tuned per use case |
| S3 Output | Single prefix | Partitioned by date/hour |
| Retention | 24h | 7 days+ |

### Checkpointing

The FlinkRunner supports checkpointing for fault tolerance. Configure via pipeline options:
```python
config["checkpoint_interval"] = 60000  # ms
config["checkpoint_mode"] = "EXACTLY_ONCE"
```

### Multi-Shard Scaling

When increasing KDS shard count, the Beam pipeline automatically distributes reads across shards. No code changes are needed — the `ReadFromKinesis` connector handles shard discovery and balancing.

---

## Configuration Reference

### CLI Arguments — `ingest_kinesis_s3.py`

| Argument | Default | Description |
|---|---|---|
| `--stream-name` | (required) | Kinesis Data Stream name |
| `--s3-bucket` | (required) | S3 bucket for output |
| `--region` | `us-east-1` | AWS region |
| `--output-prefix` | `ml-pipeline/features` | S3 output prefix |
| `--runner` | `DirectRunner` | Beam runner (`DirectRunner`, `FlinkRunner`) |
| `--initial-position` | `TRIM_HORIZON` | KDS start position (`TRIM_HORIZON`, `LATEST`) |

### CLI Arguments — `publish_kinesis_events.py`

| Argument | Default | Description |
|---|---|---|
| `--stream-name` | (required) | Target Kinesis Data Stream |
| `--region` | `us-east-1` | AWS region |
| `--events-per-second` | `2.0` | Publishing rate |
| `--total-events` | `0` (infinite) | Total events to publish (0 = run forever) |

### CLI Arguments — `trigger-ingestion.sh`

| Argument | Default | Description |
|---|---|---|
| `--total-events` | `100` | Events to produce |
| `--events-per-second` | `5.0` | Publishing rate |
| `--output-prefix` | `features` | S3 output prefix |
| `--beam-image` | `ghcr.io/.../beam:main` | Beam container image |

### Pipeline Config Keys (`create_aws_pipeline_config`)

| Key | Default | Description |
|---|---|---|
| `runner` | `DirectRunner` | Beam runner |
| `num_workers` | `2` | DirectRunner thread count |
| `input_config.type` | `kinesis` | Source type |
| `input_config.initial_position` | `TRIM_HORIZON` | KDS start position |
| `output_config.type` | `s3` | Sink type (`s3`, `feature_store`, `s3+feature_store`) |
| `window_config.type` | `fixed` | Window type (`fixed`, `sliding`, `session`) |
| `window_config.size_seconds` | `60` | Window duration |

---

## Troubleshooting

### ReadFromKinesis ImportError

```
ImportError: apache-beam[aws] is required for Kinesis I/O
```

The `ReadFromKinesis` connector requires the AWS extras. Ensure the `processing` Poetry group is installed:
```bash
poetry install --only main,processing
```

In Docker, the Beam image installs `--only main,processing` which includes `apache-beam[gcp,aws]`.

### IMDSv2 Credentials Not Working in Pods

Verify the EC2 hop limit allows container access:
```bash
# Test from inside a pod
ssh ubuntu@$INSTANCE_IP "sudo k3s kubectl run aws-test --rm -it --restart=Never \
  --image=amazon/aws-cli:latest -n ml-pipeline \
  -- s3 ls s3://rt-ml-platform-training-data-demo/ 2>&1 | head -5"
```

If this fails, check `http_put_response_hop_limit` in `ops/terraform/aws/demo/main.tf` (should be `2`).

### Beam Job OOM / Timeout

The Beam Job is configured with 512Mi request / 1Gi limit and 600s deadline. If it fails:
- Check logs: `kubectl logs job/beam-ingestion -n ml-pipeline`
- Reduce event count: `--total-events 50`
- Increase limits in `trigger-ingestion.sh` Job manifest

### Kinesis Stream Not ACTIVE

```bash
# Check stream status
aws kinesis describe-stream-summary --stream-name rt-ml-platform-demo-kds-stream \
  --query "StreamDescriptionSummary.StreamStatus"
```

If the stream was recently created, wait for it to transition from `CREATING` to `ACTIVE` (~30s).

### Stale Events from Previous Runs

Using `TRIM_HORIZON` reads all events in the 24-hour retention window, including events from previous demo runs. This is expected behavior for demos. To start fresh:
```bash
# Option 1: Wait for retention to expire (24h)
# Option 2: Recreate the stream
cd ops/terraform/aws/demo
terraform taint aws_kinesis_stream.demo_stream
terraform apply
```

### GHCR Image Pull Failures

Ensure the `ghcr-pull-secret` exists in the namespace:
```bash
ssh ubuntu@$INSTANCE_IP "sudo k3s kubectl get secret ghcr-pull-secret -n ml-pipeline"
```

If missing, re-run the bootstrap script or manually create it (see `demo-aws.md` step 1).

---

## Key Source Files

| File | Description |
|---|---|
| `src/feature_engineering/beam/pipelines.py` | Pipeline orchestration, source/sink configuration |
| `src/feature_engineering/beam/transforms.py` | FeatureExtraction, ValidateFeatures, AggregateFeatures, WriteToFeatureStore DoFns |
| `src/feature_engineering/beam/__main__.py` | CLI entry point for the pipeline |
| `scripts/data_generation/publish_kinesis_events.py` | Mock event producer |
| `scripts/demo/demo-aws/trigger-ingestion.sh` | K8s Job orchestration script |
| `ops/docker/beam/Dockerfile` | Beam runner container image |
| `ops/terraform/aws/demo/main.tf` | Kinesis stream resource |
| `ops/terraform/aws/demo/iam.tf` | Beam pipeline IAM policy |
| `ops/k8s/overlays/aws-demo/kustomization.yaml` | ConfigMap patches for stream/region |
| `.github/workflows/cd.yml` | Beam image build and push |
