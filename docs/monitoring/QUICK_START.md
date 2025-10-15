# Prometheus Monitoring Quick Start

## Quick Access

- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3001 (admin/admin123)
- **Model API Metrics**: http://localhost:8000/metrics/
- **MLflow**: http://localhost:5000

## Generate Test Traffic

```bash
bash scripts/generate_monitoring_traffic.sh
```

This will generate 20 diverse predictions to populate metrics.

## Essential Queries (Copy-Paste Ready)

### Service Health

```promql
# Check all services are UP (should all be 1)
up{job=~"model-api|redis|postgres|redpanda|prometheus"}
```

### Prediction Metrics

```promql
# Total predictions
sum(ml_predictions_total)

# Prediction rate (requests per second)
sum(rate(ml_predictions_total[5m]))

# Predictions by status breakdown
sum by (status) (ml_predictions_total)

# Success rate percentage
(sum(rate(ml_predictions_total{status="success"}[5m])) / sum(rate(ml_predictions_total[5m]))) * 100

# Error rate percentage
(sum(rate(ml_predictions_total{status="error"}[5m])) / sum(rate(ml_predictions_total[5m]))) * 100

# Cache hit rate
sum(ml_predictions_total{status="cache_hit"}) / sum(ml_predictions_total)
```

### Latency Metrics

```promql
# P50 (Median) latency
histogram_quantile(0.50, rate(ml_prediction_duration_seconds_bucket[5m]))

# P95 latency
histogram_quantile(0.95, rate(ml_prediction_duration_seconds_bucket[5m]))

# P99 latency
histogram_quantile(0.99, rate(ml_prediction_duration_seconds_bucket[5m]))

# Average latency
rate(ml_prediction_duration_seconds_sum[5m]) / rate(ml_prediction_duration_seconds_count[5m])
```

### Model Version Tracking

```promql
# Predictions by model version
sum by (model_version) (ml_predictions_total)

# Current prediction rate by version
sum by (model_version) (rate(ml_predictions_total[5m]))
```

### Infrastructure Metrics

```promql
# Redis cache hit rate
rate(redis_keyspace_hits_total[5m]) / (rate(redis_keyspace_hits_total[5m]) + rate(redis_keyspace_misses_total[5m]))

# PostgreSQL connections to MLflow database
pg_stat_database_numbackends{datname="mlflow"}

# Redis memory usage in MB
redis_memory_used_bytes / 1024 / 1024

# Redis connected clients
redis_connected_clients

# API memory usage in MB
process_resident_memory_bytes / 1024 / 1024

# API CPU usage rate
rate(process_cpu_seconds_total[5m])
```

### Capacity Planning

```promql
# Peak requests per second in last hour
max_over_time(sum(rate(ml_predictions_total[1m]))[1h:1m])

# Total predictions in last 24 hours
sum(increase(ml_predictions_total[24h]))

# Predictions per minute
sum(rate(ml_predictions_total[1m])) * 60
```

## Health Check Thresholds

Use these thresholds to assess system health:

| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| Success Rate | > 99% | 95-99% | < 95% |
| P95 Latency | < 100ms | 100-500ms | > 500ms |
| P99 Latency | < 500ms | 500ms-1s | > 1s |
| Cache Hit Rate | > 80% | 50-80% | < 50% |
| Service Up | = 1 | - | = 0 |

## Common Dashboard Panels

### Panel 1: Request Rate (Time Series)

```
Query: sum(rate(ml_predictions_total[1m]))
Legend: Requests/sec
Unit: reqps
```

### Panel 2: Latency Percentiles (Time Series)

```
Query 1 (P50): histogram_quantile(0.50, rate(ml_prediction_duration_seconds_bucket[5m]))
Query 2 (P95): histogram_quantile(0.95, rate(ml_prediction_duration_seconds_bucket[5m]))
Query 3 (P99): histogram_quantile(0.99, rate(ml_prediction_duration_seconds_bucket[5m]))
Unit: seconds
```

### Panel 3: Success Rate (Gauge)

```
Query: (sum(rate(ml_predictions_total{status="success"}[5m])) / sum(rate(ml_predictions_total[5m]))) * 100
Unit: percent (0-100)
Thresholds: 0-95 (red), 95-99 (yellow), 99-100 (green)
```

### Panel 4: Service Health (Stat)

```
Query: up{job=~"model-api|redis|postgres|redpanda"}
Value mappings: 1 = UP (green), 0 = DOWN (red)
```

### Panel 5: Cache Hit Rate (Gauge)

```
Query: sum(ml_predictions_total{status="cache_hit"}) / sum(ml_predictions_total)
Unit: percentunit (0-1)
Thresholds: 0-0.5 (red), 0.5-0.8 (yellow), 0.8-1 (green)
```

## Troubleshooting

### No metrics showing?

```bash
# Check Prometheus targets
curl http://localhost:9090/api/v1/targets | python -m json.tool

# Check Model API metrics endpoint
curl http://localhost:8000/metrics/ | head -20

# Verify all services are up
docker-compose ps
```

### Need more data?

```bash
# Generate 20 more predictions
bash scripts/generate_monitoring_traffic.sh

# Or continuously generate traffic (Ctrl+C to stop)
while true; do
  bash scripts/generate_monitoring_traffic.sh
  sleep 60
done
```

### Metrics not updating?

Prometheus scrapes at intervals:
- Model API: every 10 seconds
- Redis/Redpanda: every 15 seconds
- PostgreSQL: every 30 seconds

Wait 30 seconds and refresh your query.

## Next Steps

1. **Explore Metrics**: Open http://localhost:9090/graph and try the queries above
2. **Create Dashboards**: Import queries into Grafana at http://localhost:3001
3. **Set Up Alerts**: Add alert rules to `monitoring/prometheus/alerts/`
4. **Read Full Docs**: See [prometheus-monitoring.md](./prometheus-monitoring.md) for complete reference

## Quick Commands

```bash
# Restart Prometheus to reload config
docker-compose restart prometheus

# View Prometheus logs
docker-compose logs -f prometheus

# View Model API logs
docker-compose logs -f model-api

# Check all services health
docker-compose ps
```
