# Apache Beam Kinesis to S3 Feature Engineering Pipeline

## Overview
This document describes the data ingestion and feature engineering pipeline designed to read streaming data from Amazon Kinesis Data Streams (KDS), perform real-time feature extraction and windowed aggregation, and ingest the curated features into Amazon S3 storage for downstream Machine Learning training and analysis.

Built on **Apache Beam**, this pipeline is highly portable. It can be executed locally (at near-zero cost) for demonstration or development purposes using the `DirectRunner`, or seamlessly deployed to production streaming platforms like AWS Managed Service for Apache Flink or a portable runner cluster (`FlinkRunner`).

> For deployment on AWS (K8s Jobs, CI/CD, Terraform), see [kds-apache-beam-deployment.md](kds-apache-beam-deployment.md).

## Architecture

1. **Source**: Amazon Kinesis Data Stream (reads streaming JSON events).
2. **Transform (Feature Extraction)**: Parses JSON events, filters invalid records, and extracts feature configurations defined in `feature_config`.
3. **Transform (Windowing & Aggregation)**: Groups data into standard fixed/sliding/session windows and performs aggregations on keys (e.g., aggregating payment totals by `user_id`).
4. **Sink**: Amazon S3 (writes the valid features and the aggregated features as JSON shards for model training systems to consume).

---

## Prerequisites

### Dependencies
Before running the pipeline locally, ensure that the Apache Beam module with AWS connectors is installed. The dependencies are included in Poetry under the `processing` group.

```bash
# Install the core and streaming processing dependencies
poetry install --only main,processing
```

### AWS Configuration
Ensure you have active AWS credentials that allow reading from your target Kinesis stream and writing to your target S3 bucket.
You can configure these via standard AWS environment variables or AWS profiles natively supported by Boto3:
```bash
export AWS_ACCESS_KEY_ID="your_access_key"
export AWS_SECRET_ACCESS_KEY="your_secret_key"
export AWS_DEFAULT_REGION="us-east-1"
```

### Infrastructure Provisioning
The demonstration environment heavily leverages Terraform to automatically provision AWS resources. The target `aws_kinesis_stream` and EC2 IAM roles required for access control are automated inside `ops/terraform/aws/demo`.
To spin up the necessary stream and fetch the outputs:
```bash
cd ops/terraform/aws/demo
terraform init
terraform apply -auto-approve
# Extract your dynamically created Kinesis stream name and the S3 target bucket ARN
```

---

## Running Locally (Near-Zero Cost Demo)

For demonstration, local development, and end-to-end testing, the pipeline can be executed using the local `DirectRunner`. This leverages your local machine's cores to orchestrate the pipeline and connects to real AWS backend services (Kinesis and S3) natively without needing a dedicated computing cluster. This fulfills requirements for a **near-zero cost** pipeline demonstration.

### Generating Mock Kinesis Data
To simulate active stream producers sending events (such as mobile applications or transaction gateways), run the companion data generation script in a separate terminal. This will publish random transaction occurrences to your target Kinesis stream:

```bash
# Start simulating 2 transaction events per second
poetry run python scripts/data_generation/publish_kinesis_events.py \
    --stream-name <YOUR_PROVISIONED_KINESIS_STREAM> \
    --events-per-second 2
```

### Executing The Pipeline script
The Beam pipeline CLI entrypoint is `python -m src.feature_engineering.beam`.
Run this alongside the data generator.

### Example Invocation
```bash
poetry run python -m src.feature_engineering.beam \
    --stream-name my-demo-kinesis-stream \
    --s3-bucket my-training-bucket-ml \
    --region us-east-1 \
    --output-prefix ml-pipeline/features \
    --runner DirectRunner
```

**Parameters**:
- `--stream-name`: The existing Kinesis Data Stream name in your AWS account.
- `--s3-bucket`: The S3 destination bucket (e.g., `my-bucket`).
- `--region`: The deployment AWS region where the resources are deployed (default: `us-east-1`).
- `--output-prefix`: Folder/Path structure inside the S3 Bucket (default: `ml-pipeline/features`).
- `--runner`: Kept as `DirectRunner` to process entirely on your local machine.

---

## Pipeline Configuration Code

The AWS pipeline configuration handles injecting the proper source/sink definitions as expected by the Feature Engineering framework in `src/feature_engineering/beam/pipelines.py`.

```python
from src.feature_engineering.beam.pipelines import create_aws_pipeline_config

config = create_aws_pipeline_config(
    stream_name="my-demo-kinesis-stream",
    region="us-east-1",
    s3_bucket="my-training-bucket-ml",
    output_prefix="ml-pipeline/features"
)
# Overriding the runner to execute locally instead of remotely
config["runner"] = "DirectRunner"
```

## Running on AWS (Production)

To scale horizontally and run production throughput workloads, you can switch the runner to a managed execution engine such as `FlinkRunner` combined with AWS Managed Service for Apache Flink. 

When invoking the demo script, adjusting the runner accomplishes this:
```bash
poetry run python -m src.feature_engineering.beam \
    --stream-name prod-ingestion-stream \
    --s3-bucket prod-ml-featured-data \
    --runner FlinkRunner
```
*(Note: Refer to your broader environment infrastructure documentation for Flink Cluster configurations, checkpoints, and proper IAM Roles required for production deployments).*

## Considerations for Streaming ML Feature Engineering:
1. **Windowing Options**: Ensure `window_config` dictates how incoming streaming features scale across time gaps: Fixed, Session, or Sliding.
2. **Kinesis Starting Offset**: The framework defaults Kinesis start location to `TRIM_HORIZON` (read all available data). Other configurable options include `LATEST` (process only new data from now) and `AT_TIMESTAMP`.
3. **Data Quality Errors**: Failed transformations or invalid data schemas natively route to error streams instead of crashing the pipeline execution cleanly decoupling failure processing logic from standard flow logic.
