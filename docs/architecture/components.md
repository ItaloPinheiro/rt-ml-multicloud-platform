# System Components

## Ingestion Layer

The ingestion layer is responsible for connecting to various streaming data sources and normalizing the data into a common format.

*   **Location**: `src/ingestion/`
*   **Key Classes**: `StreamIngestion`, `StreamMessage`
*   **Supported Sources**:
    *   **Kafka**: Uses `confluent-kafka` for high-performance consumption.
    *   **AWS Kinesis**: Uses `boto3` to consume from Kinesis streams.
    *   **GCP Pub/Sub**: Uses `google-cloud-pubsub` for message pulling.

## Feature Engineering

This layer transforms raw data into machine learning features.

*   **Location**: `src/feature_engineering/`
*   **Technology**: Apache Beam
*   **Functionality**:
    *   Windowing and aggregation.
    *   Feature normalization and encoding.
    *   Writing to the Feature Store.

## Feature Store

The Feature Store is the central repository for features, ensuring consistency between training and serving.

*   **Location**: `src/feature_store/`
*   **Storage Backends**:
    *   **Redis**: "Hot" store for low-latency retrieval (<10ms).
    *   **PostgreSQL**: "Cold" store for historical data and persistence.
*   **Key Features**:
    *   Point-in-time correctness.
    *   Batch and online retrieval APIs.
    *   Feature transformations (e.g., `NumericTransform`, `CategoricalTransform`).

## Model Serving API

The serving layer exposes the models via a REST API.

*   **Location**: `src/api/`
*   **Technology**: FastAPI, Uvicorn
*   **Key Features**:
    *   **Async/Await**: Fully asynchronous request handling.
    *   **Model Caching**: Models are loaded from MLflow and cached in memory.
    *   **Batch Predictions**: Optimized endpoint for high-throughput batch scoring.
    *   **Auto-Update**: Background task to check for and load new model versions.

## Monitoring

Comprehensive observability stack.

*   **Location**: `src/monitoring/`
*   **Components**:
    *   **Prometheus**: Scrapes metrics from the API `/metrics` endpoint.
    *   **Grafana**: Visualizes metrics via dashboards.
*   **Metrics Tracked**:
    *   Prediction latency (P50, P95, P99).
    *   Throughput (RPS).
    *   Model load times.
    *   Feature store cache hit/miss rates.
    *   Data ingestion lag.
