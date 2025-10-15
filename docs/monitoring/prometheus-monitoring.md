# Prometheus Monitoring Guide

## Overview

This guide provides comprehensive information about Prometheus monitoring setup for the ML Pipeline platform. Prometheus collects metrics from all services and provides a powerful query language (PromQL) for analyzing performance and behavior.

## Access Information

- **URL**: http://localhost:9090
- **Metrics Endpoint**: http://localhost:8000/metrics (Model API)
- **Configuration**: `monitoring/prometheus/prometheus.yml`

## Architecture

### Scrape Jobs

Prometheus is configured to scrape metrics from the following services:

1. **Model API** (`model-api:8000/metrics/`)
   - Scrape interval: 10s
   - Timeout: 5s
   - Primary source for ML prediction metrics
   - Metrics: `ml_predictions_total`, `ml_prediction_duration_seconds`, `ml_model_loads_total`, `ml_batch_predictions_total`

2. **Redis Exporter** (`redis-exporter:9121/metrics`)
   - Scrape interval: 15s
   - Timeout: 5s
   - Feature cache performance metrics
   - Metrics: `redis_*` (connections, memory, keyspace, commands, etc.)

3. **PostgreSQL Exporter** (`postgres-exporter:9187/metrics`)
   - Scrape interval: 30s
   - Timeout: 10s
   - Database performance metrics
   - Metrics: `pg_*` (connections, database size, queries, locks, etc.)

4. **Redpanda** (`redpanda:9644/metrics`)
   - Scrape interval: 15s
   - Timeout: 5s
   - Message streaming metrics
   - Metrics: `redpanda_*` (throughput, latency, consumer lag, etc.)

5. **Prometheus Self-Monitoring** (`localhost:9090/metrics`)
   - Scrape interval: 30s
   - Prometheus internal metrics
   - Metrics: `prometheus_*`, `promhttp_*`

**Note**: MLflow Server does not expose native Prometheus metrics. Model registry operations are tracked via Model API metrics.

## Available Metrics

### Model Prediction Metrics

#### `ml_predictions_total`
**Type**: Counter
**Labels**: `model_name`, `model_version`, `status`
**Description**: Total number of prediction requests made to the API.
**Status values**: `success`, `error`, `cache_hit`

**Example Queries**:
```promql
# Total predictions in the last hour
increase(ml_predictions_total[1h])

# Prediction rate per second
rate(ml_predictions_total[5m])

# Success vs error rate by model
sum by (status, model_name) (rate(ml_predictions_total[5m]))

# Total predictions by model version
sum by (model_version) (ml_predictions_total)

# Current total predictions
sum(ml_predictions_total)

# Success rate percentage
(sum(rate(ml_predictions_total{status="success"}[5m])) / sum(rate(ml_predictions_total[5m]))) * 100

# Cache hit rate
sum(ml_predictions_total{status="cache_hit"}) / sum(ml_predictions_total)
```

#### `ml_prediction_duration_seconds`
**Type**: Histogram
**Labels**: `model_name`, `model_version`
**Buckets**: 0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0
**Description**: Distribution of prediction request latencies in seconds.

**Example Queries**:
```promql
# 95th percentile latency
histogram_quantile(0.95, rate(ml_prediction_duration_seconds_bucket[5m]))

# 99th percentile latency
histogram_quantile(0.99, rate(ml_prediction_duration_seconds_bucket[5m]))

# 50th percentile (median) latency
histogram_quantile(0.50, rate(ml_prediction_duration_seconds_bucket[5m]))

# Average prediction latency
rate(ml_prediction_duration_seconds_sum[5m]) / rate(ml_prediction_duration_seconds_count[5m])

# Latency by model version
histogram_quantile(0.95,
  sum by (model_version, le) (rate(ml_prediction_duration_seconds_bucket[5m]))
)

# Total time spent on predictions
sum(ml_prediction_duration_seconds_sum)
```

### Model Loading Metrics

#### `ml_model_loads_total`
**Type**: Counter
**Labels**: `model_name`, `model_version`, `status`
**Description**: Total number of model load attempts.
**Status values**: `success`, `error`

**Example Queries**:
```promql
# Total model loads
sum(ml_model_loads_total)

# Model load success rate
sum(rate(ml_model_loads_total{status="success"}[5m])) / sum(rate(ml_model_loads_total[5m]))

# Model loads by version
sum by (model_version) (ml_model_loads_total)

# Failed model loads
sum(ml_model_loads_total{status="error"})
```

#### `ml_batch_predictions_total`
**Type**: Counter
**Labels**: `model_name`, `model_version`, `status`
**Description**: Total batch prediction requests.

**Example Queries**:
```promql
# Total batch predictions
sum(ml_batch_predictions_total)

# Batch prediction rate
rate(ml_batch_predictions_total[5m])
```

### Redis Cache Metrics

Redis metrics are exposed via the **redis_exporter** sidecar.

#### `redis_keyspace_hits_total`
**Type**: Counter
**Description**: Total number of successful key lookups in Redis.

#### `redis_keyspace_misses_total`
**Type**: Counter
**Description**: Total number of failed key lookups in Redis.

**Example Queries**:
```promql
# Redis cache hit rate
rate(redis_keyspace_hits_total[5m]) /
(rate(redis_keyspace_hits_total[5m]) + rate(redis_keyspace_misses_total[5m]))

# Total cache hits
sum(redis_keyspace_hits_total)

# Cache miss rate
rate(redis_keyspace_misses_total[5m])
```

#### `redis_connected_clients`
**Type**: Gauge
**Description**: Number of client connections.

#### `redis_memory_used_bytes`
**Type**: Gauge
**Description**: Total memory allocated by Redis in bytes.

**Example Queries**:
```promql
# Redis memory usage in MB
redis_memory_used_bytes / 1024 / 1024

# Redis memory usage in GB
redis_memory_used_bytes / 1024 / 1024 / 1024

# Redis connections
redis_connected_clients

# Memory usage percentage (if max memory is set)
(redis_memory_used_bytes / redis_config_maxmemory) * 100
```

### PostgreSQL Database Metrics

PostgreSQL metrics are exposed via the **postgres_exporter** sidecar.

#### `pg_stat_database_numbackends`
**Type**: Gauge
**Labels**: `datid`, `datname`
**Description**: Number of backends currently connected to this database.

**Example Queries**:
```promql
# Active connections to MLflow database
pg_stat_database_numbackends{datname="mlflow"}

# Total database connections
sum(pg_stat_database_numbackends)

# Connections by database
sum by (datname) (pg_stat_database_numbackends)
```

#### `pg_database_size_bytes`
**Type**: Gauge
**Labels**: `datname`
**Description**: Disk space used by the database.

#### `pg_up`
**Type**: Gauge
**Description**: PostgreSQL availability (1 = up, 0 = down).

**Example Queries**:
```promql
# Database size in GB
pg_database_size_bytes{datname="mlflow"} / 1024 / 1024 / 1024

# Database availability
pg_up

# Database growth rate
rate(pg_database_size_bytes[1h])
```

### Python Application Metrics

Standard Python metrics from the Model API:

#### `python_gc_collections_total`
**Type**: Counter
**Labels**: `generation`
**Description**: Number of times this generation was collected.

#### `process_resident_memory_bytes`
**Type**: Gauge
**Description**: Resident memory size in bytes.

#### `process_cpu_seconds_total`
**Type**: Counter
**Description**: Total user and system CPU time spent in seconds.

**Example Queries**:
```promql
# Memory usage in MB
process_resident_memory_bytes / 1024 / 1024

# CPU usage rate
rate(process_cpu_seconds_total[5m])

# Garbage collection rate by generation
rate(python_gc_collections_total[5m])
```

## Common Monitoring Queries

### Performance Monitoring

```promql
# Request throughput (requests per second)
sum(rate(ml_predictions_total[5m]))

# Total predictions today
sum(increase(ml_predictions_total[24h]))

# Error rate percentage
(sum(rate(ml_predictions_total{status="error"}[5m])) /
sum(rate(ml_predictions_total[5m]))) * 100

# Success rate percentage
(sum(rate(ml_predictions_total{status="success"}[5m])) /
sum(rate(ml_predictions_total[5m]))) * 100

# Apdex score (target: 100ms, tolerable: 500ms)
# Apdex = (Satisfied + Tolerating/2) / Total
# Satisfied: requests <= 100ms, Tolerating: 100ms < requests <= 500ms
(
  sum(rate(ml_prediction_duration_seconds_bucket{le="0.1"}[5m])) +
  (sum(rate(ml_prediction_duration_seconds_bucket{le="0.5"}[5m])) -
   sum(rate(ml_prediction_duration_seconds_bucket{le="0.1"}[5m]))) / 2
) / sum(rate(ml_prediction_duration_seconds_count[5m]))

# Cache effectiveness
sum(ml_predictions_total{status="cache_hit"}) / sum(ml_predictions_total)
```

### Capacity Planning

```promql
# Predictions per minute by model
sum by (model_name) (rate(ml_predictions_total[1m])) * 60

# Predictions per second by version
sum by (model_version) (rate(ml_predictions_total[5m]))

# Peak request rate in last 24 hours
max_over_time(
  sum(rate(ml_predictions_total[5m]))[24h:5m]
)

# Resource utilization trend
avg_over_time(process_resident_memory_bytes[1h]) / 1024 / 1024

# Database connection usage
avg_over_time(pg_stat_database_numbackends{datname="mlflow"}[1h])
```

### SLI/SLO Monitoring

```promql
# SLI: 95% of requests < 100ms (0.1 seconds)
histogram_quantile(0.95, rate(ml_prediction_duration_seconds_bucket[5m])) < 0.1

# SLI: 99% of requests < 500ms (0.5 seconds)
histogram_quantile(0.99, rate(ml_prediction_duration_seconds_bucket[5m])) < 0.5

# SLO: 99.9% availability (success rate)
(
  sum(rate(ml_predictions_total{status="success"}[5m])) /
  sum(rate(ml_predictions_total[5m]))
) > 0.999

# Error budget burn rate (for 99.9% SLO)
(1 - (
  sum(rate(ml_predictions_total{status="success"}[1h])) /
  sum(rate(ml_predictions_total[1h]))
))

# Service availability
min(up{job=~"model-api|redis|postgres"})
```

## Alerting Rules

Create alert rules in `monitoring/prometheus/alerts/` directory:

### High Error Rate Alert

```yaml
groups:
  - name: ml_pipeline_alerts
    interval: 30s
    rules:
      - alert: HighErrorRate
        expr: |
          (
            sum(rate(ml_predictions_total{status="error"}[5m])) /
            sum(rate(ml_predictions_total[5m]))
          ) > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High error rate detected"
          description: "Error rate is {{ $value | humanizePercentage }} over the last 5 minutes"
```

### High Latency Alert

```yaml
      - alert: HighPredictionLatency
        expr: |
          histogram_quantile(0.95,
            rate(ml_prediction_duration_seconds_bucket[5m])
          ) > 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High prediction latency"
          description: "95th percentile latency is {{ $value }}s"
```

### Critical Latency Alert

```yaml
      - alert: CriticalPredictionLatency
        expr: |
          histogram_quantile(0.95,
            rate(ml_prediction_duration_seconds_bucket[5m])
          ) > 1.0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Critical prediction latency"
          description: "95th percentile latency is {{ $value }}s (threshold: 1s)"
```

### Model API Service Down

```yaml
      - alert: ModelAPIDown
        expr: up{job="model-api"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Model API service is down"
          description: "The ML Model API has been down for more than 1 minute"
```

### Database Connection Issues

```yaml
      - alert: HighDatabaseConnections
        expr: pg_stat_database_numbackends{datname="mlflow"} > 80
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High number of database connections"
          description: "MLflow database has {{ $value }} active connections"
```

### Cache Performance Degradation

```yaml
      - alert: LowCacheHitRate
        expr: |
          (
            rate(redis_keyspace_hits_total[5m]) /
            (rate(redis_keyspace_hits_total[5m]) + rate(redis_keyspace_misses_total[5m]))
          ) < 0.5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Low Redis cache hit rate"
          description: "Cache hit rate is {{ $value | humanizePercentage }}"
```

### No Predictions Being Made

```yaml
      - alert: NoPredictions
        expr: rate(ml_predictions_total[5m]) == 0
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "No predictions being made"
          description: "The API hasn't received any prediction requests in the last 10 minutes"
```

## Best Practices

### Query Optimization

1. **Use rate() for counters**: Always use `rate()` or `increase()` with counters
2. **Appropriate time ranges**: Use 5m for recent data, 1h for trends
3. **Limit label cardinality**: Avoid high-cardinality labels (e.g., user IDs)
4. **Use recording rules**: Pre-calculate expensive queries
5. **Avoid regex matching**: Use label matching when possible

### Recording Rules Example

```yaml
groups:
  - name: ml_pipeline_recording_rules
    interval: 30s
    rules:
      - record: job:prediction_success_rate:5m
        expr: |
          sum by (model_name) (rate(ml_predictions_total{status="success"}[5m])) /
          sum by (model_name) (rate(ml_predictions_total[5m]))

      - record: job:prediction_latency_p95:5m
        expr: |
          histogram_quantile(0.95,
            sum by (model_name, le) (rate(ml_prediction_duration_seconds_bucket[5m]))
          )

      - record: job:prediction_latency_p99:5m
        expr: |
          histogram_quantile(0.99,
            sum by (model_name, le) (rate(ml_prediction_duration_seconds_bucket[5m]))
          )

      - record: job:prediction_throughput:1m
        expr: |
          sum(rate(ml_predictions_total[1m])) * 60

      - record: job:cache_hit_rate:5m
        expr: |
          sum(ml_predictions_total{status="cache_hit"}) /
          sum(ml_predictions_total)
```

### Retention and Storage

- Default retention: 15 days
- Adjust in `docker-compose.yml`: `--storage.tsdb.retention.time=30d`
- Monitor disk usage: `prometheus_tsdb_storage_blocks_bytes`
- Use remote storage for long-term retention

## Troubleshooting

### Metrics Not Appearing

1. Check scrape targets: http://localhost:9090/targets
2. Verify service health: `curl http://localhost:8000/metrics`
3. Check Prometheus logs: `docker-compose logs prometheus`
4. Validate configuration: `promtool check config prometheus.yml`

### High Memory Usage

1. Reduce retention period
2. Decrease scrape frequency for less critical services
3. Enable metric relabeling to drop unnecessary metrics
4. Use recording rules instead of complex queries

### Query Performance Issues

1. Use Prometheus query analyzer: http://localhost:9090/graph
2. Limit time range and step size
3. Use recording rules for frequently used queries
4. Add indexes with label matchers

## Integration with Grafana

Prometheus is pre-configured as the default datasource in Grafana:
- **Datasource name**: Prometheus
- **URL**: http://prometheus:9090
- **Access**: Proxy mode
- **Default**: Yes

See [grafana-dashboards.md](./grafana-dashboards.md) for visualization guidance.

## References

- [Prometheus Documentation](https://prometheus.io/docs/)
- [PromQL Basics](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Best Practices](https://prometheus.io/docs/practices/naming/)
- [Alerting Rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
