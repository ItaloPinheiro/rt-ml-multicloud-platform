# System Components

## Ingestion Layer

The ingestion layer is responsible for connecting to various streaming data sources and normalizing the data into a common format.

*   **Location**: `src/ingestion/`
*   **Key Classes**: `StreamIngestion`, `StreamMessage`
*   **Supported Sources**:
    *   **Kafka**: Uses `confluent-kafka` for high-performance consumption with manual offset commits.
    *   **AWS Kinesis**: Uses `boto3` to consume from Kinesis streams with shard iterator management.
    *   **GCP Pub/Sub**: Uses `google-cloud-pubsub` for message pulling with ack deadline handling.
*   **Delivery Semantics**: At-least-once across all adapters. Idempotency handled at the storage layer.

## Feature Engineering

This layer transforms raw streaming data into machine learning features using Apache Beam.

*   **Location**: `src/feature_engineering/`
*   **Technology**: Apache Beam (DirectRunner for demo, FlinkRunner/Dataflow for production)
*   **Functionality**:
    *   Temporal, categorical, and numerical feature extraction.
    *   Configurable windowing (fixed, sliding, session) with allowed lateness.
    *   Data quality validation (null checks, range validation, schema enforcement).
    *   Writing features and aggregations to S3 as JSON files.
*   **Feature Store Sink**: The `WriteToFeatureStore` Beam DoFn writes features directly to the Feature Store using batched bulk upserts (`bulk_put_features`). Configurable batch size, TTL, and entity key field. Failed writes are routed to a dead-letter tagged output.
*   **Training Data Assembly**: The `assemble_training_data` module supports two sources: `beam` (joins per-record features with windowed aggregations from S3 JSON-lines) and `feature_store` (reads directly from PostgreSQL, pivots EAV to wide format). Supports CSV and Parquet output formats.

## Feature Store

The Feature Store provides a dual-tier storage abstraction for feature management.

*   **Location**: `src/feature_store/`
*   **Storage Backends**:
    *   **Redis**: Hot store for low-latency retrieval.
    *   **PostgreSQL**: Cold store for historical data and persistence via `session.merge()` upserts.
*   **Key Features**:
    *   Composite unique key `(entity_id, feature_group, feature_name, event_timestamp)` for idempotent writes.
    *   Batch and online retrieval APIs.
    *   Feature transformations (e.g., `NumericTransform`, `CategoricalTransform`).
*   **Beam Integration**: The `WriteToFeatureStore` DoFn writes Beam pipeline output directly to the Feature Store using `bulk_put_features()` with batched Redis pipeline writes and PostgreSQL `INSERT ... ON CONFLICT DO UPDATE` upserts.
*   **Training Integration**: `ModelTrainer.load_data_from_feature_store()` reads features via SQLAlchemy Core `select()` with `yield_per(10_000)`, pivots EAV to wide format, and applies configurable labeling strategies.
*   **API Integration**: The `/predict` endpoint accepts an optional `entity_id` to fetch features from the Feature Store at inference time. Additional endpoints (`/features/groups`, `/features/stats`, `/features/{entity_id}`) provide feature visibility.
*   **Observability**: Prometheus metrics track ingestion throughput (`feature_ingestion_total`), latency (`feature_ingestion_duration_seconds`), and entity/feature counts per group.

## MLflow (Experiment Tracking & Model Registry)

MLflow is the central hub connecting training, evaluation, and serving. It stores experiment metadata, model artifacts, and manages production promotion.

*   **Location**: Deployed as a K8s Deployment (`mlflow-service`) with a PostgreSQL backend and S3/MinIO artifact store.
*   **K8s Access**: NodePort `:30500` (AWS demo), `:30000` (local-k8s), `:5000` (Docker Compose).
*   **Roles in the platform**:
    *   **Experiment Tracking**: Training jobs log hyperparameters, metrics (accuracy, F1, precision, recall), and model artifacts per run.
    *   **Model Registry**: Registered models with versioning. The evaluation gate queries the registry to compare challenger vs champion.
    *   **Production Alias**: MLflow 2.9+ alias API (`production` alias) determines which model version the API serves. Tag-based fallback (`deployment_status`) for older servers.
    *   **Artifact Storage**: Model binaries (pickle/PyFunc) stored in S3 (AWS demo) or MinIO (local demo). The API downloads artifacts at load time via `mlflow.pyfunc.load_model`.
*   **Backend Store**: PostgreSQL stores experiment metadata, run parameters, metrics, and model registry state.

## Model Training & Evaluation

Training and evaluation run as Kubernetes Jobs with MLflow tracking.

*   **Location**: `src/models/training/`, `src/models/evaluation/`
*   **Technology**: scikit-learn, MLflow, K8s Jobs
*   **Training Job**:
    *   **S3 mode** (default): Init container downloads training CSV from S3 to an emptyDir volume.
    *   **Feature Store mode** (`--use-feature-store`): Reads directly from Feature Store PostgreSQL, no init container needed. K8s manifest: `job-model-training-fs.yaml`.
    *   Main container fits the model and logs metrics/artifacts to MLflow with `data_source` lineage param.
    *   Supports configurable hyperparameters (n-estimators, max-depth, class-weight).
*   **Evaluation Gate**:
    *   Runs as a separate K8s Job after training completes.
    *   Compares challenger vs champion on accuracy and F1 score.
    *   Enforces minimum accuracy threshold (0.80) before comparison.
    *   Promotes via MLflow alias API with tag-based fallback.

## Model Serving API

The serving layer exposes models via a REST API with automatic updates.

*   **Location**: `src/api/`
*   **Technology**: FastAPI, Uvicorn
*   **Key Features**:
    *   **Async/Await**: Fully asynchronous request handling with `run_in_executor` for blocking I/O.
    *   **Model Caching**: Models loaded from MLflow and cached in-memory as a Python dict.
    *   **Prediction Caching**: Redis caches inference results keyed by `model:version:features_hash` (5-min TTL). Version-aware keys prevent stale results after model swaps.
    *   **Auto-Update**: `ModelUpdateManager` background task polls MLflow every 60s, loads new versions, validates with a test prediction, and atomically swaps the dict reference.
    *   **Batch Predictions**: Optimized endpoint for high-throughput batch scoring.

## Monitoring

Comprehensive observability stack.

*   **Location**: `src/monitoring/`
*   **Components**:
    *   **Prometheus**: Scrapes metrics from the API `/metrics` endpoint.
    *   **Grafana**: Visualizes metrics via 6 dashboards (uptime, model performance, errors, resources, etc.).
*   **Metrics Tracked**:
    *   Prediction latency (P50, P95, P99 histograms).
    *   Throughput (requests per second).
    *   Model load times and active model count.
    *   Dependency health (MLflow, Redis).
    *   Prediction cache hits vs misses.
*   **Alerting**: Prometheus alert rules for `HighPredictionLatency`, `LowCacheHitRate`, `ModelAPIDown`.
