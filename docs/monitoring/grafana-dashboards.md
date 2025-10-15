# Grafana Dashboards Guide

## Overview

This guide provides comprehensive information about Grafana dashboards for monitoring the ML Pipeline platform. Grafana provides rich visualizations and alerting capabilities for all metrics collected by Prometheus.

## Access Information

- **URL**: http://localhost:3001
- **Default Credentials**:
  - Username: `admin`
  - Password: `admin123`
- **Configuration**: `monitoring/grafana/`

## Initial Setup

### First Login

1. Navigate to http://localhost:3001
2. Login with default credentials (admin/admin123)
3. (Optional) Change password when prompted
4. Prometheus datasource is pre-configured and ready to use

### Datasource Configuration

The Prometheus datasource is automatically provisioned with:
- **Name**: Prometheus
- **Type**: Prometheus
- **URL**: http://prometheus:9090
- **Access**: Server (proxy)
- **Default**: Yes

Configuration file: `monitoring/grafana/datasources/prometheus.yml`

## Dashboard Organization

Dashboards are organized into folders for easy navigation:

### ML Pipeline Folder
- Model Performance Dashboard
- Feature Store Dashboard
- System Resources Dashboard
- Data Ingestion Dashboard
- Error Tracking Dashboard

## Recommended Dashboards

### 1. Model Performance Dashboard

**Purpose**: Monitor ML model prediction performance, latency, and throughput

#### Panels to Include:

**Prediction Throughput**
```
Panel Type: Graph
Query: sum(rate(ml_pipeline_prediction_requests_total[5m]))
Unit: requests/sec
Description: Real-time prediction request rate
```

**Prediction Latency (P50, P95, P99)**
```
Panel Type: Graph
Queries:
  - P50: histogram_quantile(0.50, rate(ml_pipeline_prediction_duration_seconds_bucket[5m]))
  - P95: histogram_quantile(0.95, rate(ml_pipeline_prediction_duration_seconds_bucket[5m]))
  - P99: histogram_quantile(0.99, rate(ml_pipeline_prediction_duration_seconds_bucket[5m]))
Unit: seconds
Thresholds: Warning at 0.5s, Critical at 1.0s
```

**Success vs Error Rate**
```
Panel Type: Pie Chart
Queries:
  - Success: sum(rate(ml_pipeline_prediction_requests_total{status="success"}[5m]))
  - Error: sum(rate(ml_pipeline_prediction_requests_total{status="error"}[5m]))
Display: Percentage
```

**Predictions by Model Version**
```
Panel Type: Bar Gauge
Query: sum by (model_version) (rate(ml_pipeline_prediction_requests_total[5m]))
Orientation: Horizontal
```

**Request Heatmap**
```
Panel Type: Heatmap
Query: sum(increase(ml_pipeline_prediction_duration_seconds_bucket[1m])) by (le)
Format: Heatmap
Description: Distribution of request latencies over time
```

**Models Loaded**
```
Panel Type: Stat
Query: ml_pipeline_models_loaded_total
Color: Green
Description: Current number of loaded models
```

**Model Load Times**
```
Panel Type: Bar Chart
Query: avg by (model_name) (ml_pipeline_model_load_duration_seconds_sum)
Unit: seconds
Description: Average time to load each model
```

### 2. Feature Store Dashboard

**Purpose**: Monitor feature cache performance and database operations

#### Panels to Include:

**Cache Hit Rate**
```
Panel Type: Gauge
Query: sum(rate(ml_pipeline_feature_cache_hits_total[5m])) /
       (sum(rate(ml_pipeline_feature_cache_hits_total[5m])) +
        sum(rate(ml_pipeline_feature_cache_misses_total[5m])))
Unit: percentunit (0-1)
Thresholds: 0-0.5 (red), 0.5-0.8 (yellow), 0.8-1.0 (green)
```

**Cache Hits vs Misses**
```
Panel Type: Time Series
Queries:
  - Hits: sum(rate(ml_pipeline_feature_cache_hits_total[5m]))
  - Misses: sum(rate(ml_pipeline_feature_cache_misses_total[5m]))
Fill: 50% opacity
```

**Feature Requests by Group**
```
Panel Type: Table
Query: sum by (feature_group) (ml_pipeline_feature_requests_total)
Columns: Feature Group, Total Requests, Request Rate
Sort: By total requests descending
```

**Feature Store Operations**
```
Panel Type: Stacked Bar Chart
Query: sum by (operation) (rate(ml_pipeline_feature_requests_total[5m]))
Legend: Bottom
```

**Feature Request Latency**
```
Panel Type: Graph
Query: rate(ml_pipeline_feature_requests_total[5m])
Group by: operation, status
```

### 3. System Resources Dashboard

**Purpose**: Monitor system-level metrics (CPU, memory, disk, network)

#### Panels to Include:

**CPU Usage**
```
Panel Type: Time Series
Query: ml_pipeline_cpu_usage_percent
Unit: percent (0-100)
Thresholds: Warning at 70%, Critical at 90%
Fill: Gradient
```

**Memory Usage**
```
Panel Type: Time Series
Query: ml_pipeline_memory_usage_bytes / 1024 / 1024
Unit: MB
Display: Area graph
```

**Memory Usage Gauge**
```
Panel Type: Gauge
Query: ml_pipeline_memory_usage_bytes / 1024 / 1024 / 1024
Unit: GB
Max: Container memory limit
Thresholds: 0-70% (green), 70-85% (yellow), 85-100% (red)
```

**Service Health Status**
```
Panel Type: Stat Panel
Queries:
  - Model API: up{job="model-api"}
  - MLflow: up{job="mlflow-server"}
  - Redis: up{job="redis"}
  - Redpanda: up{job="redpanda"}
Value Mappings: 1=UP (green), 0=DOWN (red)
```

**Container Status Matrix**
```
Panel Type: Status History
Query: up{job=~".*"}
Display: Show all services status over time
```

### 4. Data Ingestion Dashboard

**Purpose**: Monitor streaming data ingestion from Kafka/Kinesis/Pub/Sub

#### Panels to Include:

**Message Ingestion Rate**
```
Panel Type: Graph
Query: sum by (source) (rate(ml_pipeline_ingestion_messages_total[5m]))
Legend: Show by source (kafka, kinesis, pubsub)
Unit: messages/sec
```

**Ingestion Lag**
```
Panel Type: Graph
Query: ml_pipeline_ingestion_lag_seconds
Unit: seconds
Thresholds: Warning at 30s, Critical at 60s
Alert: Create alert when lag > 60s
```

**Total Messages Ingested**
```
Panel Type: Stat
Query: sum(ml_pipeline_ingestion_messages_total)
Format: Number with commas
```

**Ingestion Error Rate**
```
Panel Type: Graph
Query: sum by (source) (rate(ml_pipeline_ingestion_messages_total{status="error"}[5m]))
Color: Red
Display: Lines with points
```

**Messages by Source**
```
Panel Type: Pie Chart
Query: sum by (source) (rate(ml_pipeline_ingestion_messages_total[5m]))
Display: Donut chart with percentages
```

### 5. Error Tracking Dashboard

**Purpose**: Monitor and troubleshoot errors across all components

#### Panels to Include:

**Error Rate Trend**
```
Panel Type: Graph
Query: sum by (component) (rate(ml_pipeline_errors_total[5m]))
Display: Stacked area
Legend: Right side
```

**Top 10 Error Types**
```
Panel Type: Table
Query: topk(10, sum by (error_type, component) (ml_pipeline_errors_total))
Columns: Error Type, Component, Count, Last Seen
Sort: By count descending
```

**Errors by Component**
```
Panel Type: Bar Gauge
Query: sum by (component) (rate(ml_pipeline_errors_total[5m]))
Orientation: Horizontal
Color: Red gradient
```

**Recent Error Spikes**
```
Panel Type: Graph
Query: delta(ml_pipeline_errors_total[1m])
Display: Bar chart
Alert: When > 10 errors in 1 minute
```

**Error Rate Heatmap**
```
Panel Type: Heatmap
Query: sum by (component) (increase(ml_pipeline_errors_total[5m]))
Display: Color intensity by error count
```

## Dashboard Variables

Create template variables for dynamic filtering:

### Environment Variable
```
Name: environment
Type: Query
Query: label_values(ml_pipeline_prediction_requests_total, environment)
Multi-value: No
Include All: No
```

### Model Name Variable
```
Name: model
Type: Query
Query: label_values(ml_pipeline_prediction_requests_total, model_name)
Multi-value: Yes
Include All: Yes
Current: All
```

### Time Range Variable
```
Name: interval
Type: Interval
Values: 1m, 5m, 10m, 30m, 1h
Auto: Yes
```

### Feature Group Variable
```
Name: feature_group
Type: Query
Query: label_values(ml_pipeline_feature_requests_total, feature_group)
Multi-value: Yes
Include All: Yes
```

## Using Variables in Queries

Replace hardcoded values with variables:

```promql
# Before
sum(rate(ml_pipeline_prediction_requests_total{model_name="fraud_detector"}[5m]))

# After
sum(rate(ml_pipeline_prediction_requests_total{model_name=~"$model"}[$interval]))
```

## Alerting in Grafana

### Configure Alert Notifications

1. Go to **Alerting** → **Contact points**
2. Add notification channels:
   - Email
   - Slack
   - PagerDuty
   - Webhook

### Create Dashboard Alerts

**High Error Rate Alert**
```
Panel: Error Rate Trend
Condition: WHEN avg() OF query(A, 5m, now) IS ABOVE 0.05
Frequency: Evaluate every 1m for 5m
Notifications: Send to #ml-ops-alerts
Message: "Error rate is {{ $value }}% - check logs immediately"
```

**Prediction Latency Alert**
```
Panel: Prediction Latency P95
Condition: WHEN last() OF query(A, 5m, now) IS ABOVE 0.5
Frequency: Evaluate every 1m for 5m
Notifications: Send to #ml-ops-alerts
Message: "P95 latency is {{ $value }}s - performance degraded"
```

**Model Not Loaded Alert**
```
Panel: Models Loaded
Condition: WHEN last() OF query(A, 1m, now) IS BELOW 1
Frequency: Evaluate every 30s for 2m
Notifications: Send to #ml-ops-critical
Message: "No models loaded! Service is degraded"
```

## Visualization Best Practices

### 1. Panel Selection Guidelines

- **Gauges**: Current state (CPU%, memory, cache hit rate)
- **Graphs**: Trends over time (latency, throughput)
- **Stat Panels**: Single values (total requests, models loaded)
- **Bar Charts**: Comparisons (requests by model, errors by component)
- **Heatmaps**: Distribution analysis (latency distribution)
- **Tables**: Detailed breakdowns (top errors, feature groups)

### 2. Color Schemes

**Performance Metrics**:
- Green: Good (< threshold)
- Yellow: Warning (threshold - 1.5x)
- Red: Critical (> 1.5x threshold)

**Status Indicators**:
- Green: Healthy/Success
- Red: Unhealthy/Error
- Blue: Info/In-progress

### 3. Time Ranges

- **Real-time monitoring**: Last 15 minutes
- **Performance analysis**: Last 1 hour
- **Capacity planning**: Last 24 hours - 7 days
- **Incident investigation**: Custom range

### 4. Refresh Rates

- **Critical dashboards**: 10s
- **Performance dashboards**: 30s
- **Resource dashboards**: 1m
- **Historical dashboards**: 5m

## Dashboard JSON Export/Import

### Export Dashboard

1. Go to dashboard settings (gear icon)
2. Click **JSON Model**
3. Copy JSON
4. Save to `monitoring/grafana/dashboards/`

### Import Dashboard

1. Click **+** → **Import**
2. Paste JSON or upload file
3. Select Prometheus datasource
4. Click **Import**

### Version Control

Store dashboard JSON in Git:
```bash
monitoring/grafana/dashboards/
├── model-performance.json
├── feature-store.json
├── system-resources.json
├── data-ingestion.json
└── error-tracking.json
```

## Advanced Features

### 1. Annotations

Add deployment markers:
```
Query: ALERTS{alertname="DeploymentStarted"}
```

### 2. Links Between Dashboards

Create dashboard links for navigation:
- Model Performance → Error Tracking (for errors)
- Feature Store → System Resources (for cache issues)
- Data Ingestion → Error Tracking (for ingestion errors)

### 3. Drill-down Panels

Add data links to panels:
```
URL: /d/errors-dashboard?var-component=${__field.labels.component}
Title: View errors for ${__field.labels.component}
```

### 4. Panel Repeating

Create dynamic panels based on variables:
```
Repeat: By $model variable
Direction: Horizontal
Max per row: 4
```

## Mobile App

Grafana mobile app is available for iOS and Android:
- View dashboards on the go
- Receive push notifications
- Acknowledge alerts
- Quick performance checks

## Troubleshooting

### Dashboard Not Loading

1. Check Prometheus datasource connection
2. Verify metric names in queries
3. Check time range selection
4. Review Grafana logs: `docker-compose logs grafana`

### No Data in Panels

1. Verify Prometheus is scraping: http://localhost:9090/targets
2. Check metric availability: http://localhost:8000/metrics
3. Validate PromQL query in Prometheus first
4. Check time range and refresh interval

### Slow Dashboard Performance

1. Reduce time range
2. Increase refresh interval
3. Use recording rules in Prometheus
4. Limit number of series in queries
5. Use query caching

### Permission Issues

1. Check user roles (Viewer, Editor, Admin)
2. Verify folder permissions
3. Check datasource permissions
4. Review team access settings

## Sharing Dashboards

### Snapshot

Create time-bound shareable links:
1. Click **Share** on dashboard
2. Click **Snapshot**
3. Set expiration time
4. Copy link

### Public Dashboard

Make dashboard publicly accessible:
1. Enable anonymous access in grafana.ini
2. Set public dashboard permissions
3. Share URL (no authentication required)

### Embed Panels

Embed panels in external apps:
```html
<iframe src="http://localhost:3001/d-solo/abc123/dashboard?orgId=1&panelId=2"
        width="800" height="400"></iframe>
```

## Maintenance

### Regular Tasks

**Weekly**:
- Review alert effectiveness
- Check dashboard relevance
- Update thresholds based on SLOs

**Monthly**:
- Archive unused dashboards
- Update documentation
- Review and optimize queries

**Quarterly**:
- Dashboard audit and cleanup
- Team training on new features
- Update alerting strategies

## References

- [Grafana Documentation](https://grafana.com/docs/grafana/latest/)
- [Dashboard Best Practices](https://grafana.com/docs/grafana/latest/dashboards/)
- [Alerting Guide](https://grafana.com/docs/grafana/latest/alerting/)
- [PromQL in Grafana](https://grafana.com/docs/grafana/latest/datasources/prometheus/)
- [Prometheus Monitoring Guide](./prometheus-monitoring.md)
