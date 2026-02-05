# Monitoring Module

The monitoring module (`src/monitoring`) provides observability for the entire platform.

## Metrics Collection

We use **Prometheus** for metrics collection. The `MetricsCollector` class provides a unified interface for recording:

*   **Counters**: Monotonically increasing values (e.g., total requests).
*   **Gauges**: Instantaneous values (e.g., memory usage, queue lag).
*   **Histograms**: Distributions of values (e.g., request latency).

## Key Metrics

| Metric Name | Type | Description |
|-------------|------|-------------|
| `ml_prediction_requests_total` | Counter | Total prediction requests by model/status |
| `ml_prediction_duration_seconds` | Histogram | Latency distribution for predictions |
| `ml_feature_cache_hits_total` | Counter | Feature Store cache efficiency |
| `ml_ingestion_lag_seconds` | Gauge | Time difference between event creation and ingestion |

## Health Checks

The `src/monitoring/health.py` module provides health check logic for:
*   **API Liveness**: Is the server running?
*   **Dependencies**: Are Redis, DB, and MLflow reachable?

## Grafana Dashboards

Pre-built dashboards are available in `monitoring/grafana/dashboards/`. They visualize:
1.  **System Health**: CPU, Memory, Network.
2.  **Model Performance**: Latency, Throughput, Error Rates.
3.  **Data Quality**: Feature drift (future scope), Null rates.
