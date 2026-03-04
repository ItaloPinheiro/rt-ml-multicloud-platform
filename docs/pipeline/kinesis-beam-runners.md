# Kinesis IO and Beam Runners on AWS

How Apache Beam reads from Kinesis, which runners support it, and what each deployment option costs in production.

## Why Kinesis IO Is a Cross-Language Transform

Apache Beam's `ReadFromKinesis` is **not a native Python implementation**. It is a cross-language transform backed by the Java SDK:

```
Python Pipeline Code
    |
    v
Python SDK wrapper (apache_beam.io.kinesis)
    |  gRPC at pipeline construction time
    v
Java Expansion Service (beam-sdks-java-io-kinesis-expansion-service.jar)
    |
    v
Java KinesisIO (uses AWS KCL for shard management, checkpointing, resharding)
    |
    v
Expanded pipeline graph returned to Python runner
```

**Reasons:**

1. **KCL is Java-native.** The AWS Kinesis Client Library handles shard management, lease coordination, checkpointing, and resharding -- all implemented in Java. No Python equivalent exists.
2. **Write once, reuse everywhere.** Beam's cross-language framework (introduced ~2019) lets one robust Java implementation serve Python, Go, and other SDKs.
3. **Contributor priority.** Native Python IO connectors exist only for Google-first services (BigQuery, Pub/Sub, GCS) and generic protocols (Kafka, files). AWS-specific connectors reuse Java.

## Runner Compatibility

| Runner | Cross-Language Kinesis IO | Notes |
|--------|--------------------------|-------|
| **DirectRunner** | No | No portable expansion protocol support |
| **FlinkRunner (portable)** | Yes | Officially supported |
| **SparkRunner (portable)** | Yes | Officially supported |
| **DataflowRunner** | No | GCP only, not applicable for Kinesis |

**DirectRunner limitation:** The cross-language transform requires a Java expansion service and the portable runner protocol. DirectRunner does not implement this protocol, so `ReadFromKinesis` imports as `None`. For DirectRunner workloads (local dev, demos, bounded batches), use the boto3-based fallback (see below).

## Production Deployment Options on AWS

### Option 1: AWS Managed Service for Apache Flink

Fully managed Flink cluster running Beam pipelines with `FlinkRunner`.

- **Cost:** ~$0.11/KPU-hour (1 KPU = 1 vCPU + 4GB). Minimum ~$80/month for a small app.
- **Pros:** Zero cluster management, auto-scaling, native Kinesis integration, cross-language transforms work.
- **Cons:** Natively supports Java/Scala Flink apps. Python SDK requires packaging with the Flink job or running a self-managed Flink cluster with portable runner.

### Option 2: Self-Managed Flink on EKS/EC2

Run your own Flink cluster on Kubernetes (EKS) or EC2 instances.

- **Cost:** EKS $73/month control plane + EC2 compute (e.g., 3x m5.large ~$200/month).
- **Pros:** Full control, cross-language transforms work, Python SDK supported via portable runner.
- **Cons:** Cluster management burden (scaling, upgrades, monitoring, Flink operator).

### Option 3: EMR with SparkRunner

AWS EMR running Spark with Beam's SparkRunner.

- **Cost:** EMR pricing (~$0.05-0.10/hour per node + EC2).
- **Pros:** Managed Spark, cross-language supported, good for batch and micro-batch.
- **Cons:** Spark Structured Streaming is micro-batch (higher latency than Flink).

### Option 4: boto3 on ECS/K8s (Demo / Bounded Workloads)

Use boto3 to poll Kinesis records, feed into Beam DirectRunner for transforms.

- **Cost:** Just compute (existing EC2/ECS/K8s pod).
- **Pros:** Simple, no JVM dependency, works everywhere, no additional infrastructure.
- **Cons:** Not true streaming (poll-based), no auto-checkpointing, no resharding support. Suitable for bounded workloads only.

## Demo vs Production Comparison

```
                    Production                          Demo
-----------------------------------------------------------------------
Runner              FlinkRunner (portable)              DirectRunner
Infrastructure      Flink on EKS or Managed Flink       K8s Job on EC2
Kinesis IO          Cross-language (Java expansion)      boto3 polling
Processing          True streaming, windowing            Bounded batch
Checkpointing       Flink savepoints                     None needed
Scaling             Flink parallelism / auto-scale       Single pod
Monthly cost        ~$200-400 minimum                    ~$0 (reuses EC2)
```

**Key point:** The same Beam pipeline code (`pipelines.py`, `transforms.py`) works with both runners. Only the runner flag and input source change. Feature extraction, validation, windowing, and aggregation logic is identical.

## Migration Path

1. **Current (demo):** DirectRunner + boto3 Kinesis reader on K3s single node.
2. **Next step:** Add Flink overlay (`ops/k8s/overlays/flink/`) with FlinkRunner config. Switch `--runner=FlinkRunner` and the native `ReadFromKinesis` cross-language transform activates.
3. **Production:** AWS Managed Flink or self-managed Flink on EKS. Same pipeline code, just infrastructure changes.

See `kds-apache-beam-deployment.md` for the full deployment guide and `apache-beam-kinesis-to-s3.md` for the pipeline architecture.
