import json
import os

DASHBOARDS_DIR = "ops/monitoring/grafana/dashboards"
os.makedirs(DASHBOARDS_DIR, exist_ok=True)


def create_dashboard(uid, title, panels):
    return {
        "uid": uid,
        "title": title,
        "panels": panels,
        "schemaVersion": 36,
        "timezone": "browser",
        "refresh": "1m",
        # Template variable for filtering by model name across all panels
        "templating": {
            "list": [
                {
                    "name": "model_name",
                    "type": "query",
                    "label": "Model",
                    "query": "label_values(ml_predictions_total, model_name)",
                    "current": {"text": "All", "value": "$__all"},
                    "includeAll": True,
                    "multi": True,
                    "refresh": 2,
                }
            ]
        },
    }


def stat_panel(
    title, x, y, expr, mappings=None, thresholds=None, unit="none", decimals=0
):
    if not mappings:
        mappings = []
    if not thresholds:
        thresholds = {"mode": "absolute", "steps": [{"color": "green", "value": None}]}

    return {
        "type": "stat",
        "title": title,
        "gridPos": {"x": x, "y": y, "w": 6, "h": 6},
        "targets": [{"expr": expr, "refId": "A"}],
        "options": {"colorMode": "value", "graphMode": "none", "justifyMode": "auto"},
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "decimals": decimals,
                "mappings": mappings,
                "thresholds": thresholds,
            },
            "overrides": [],
        },
    }


def timeseries_panel(title, x, y, targets, unit="short", w=12, h=8):
    return {
        "type": "timeseries",
        "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [
            {
                "expr": t["expr"],
                "legendFormat": t.get("legend", ""),
                "refId": chr(65 + i),
            }
            for i, t in enumerate(targets)
        ],
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}},
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "custom": {
                    "drawStyle": "line",
                    "lineInterpolation": "linear",
                    "lineWidth": 1,
                    "fillOpacity": 10,
                },
            },
            "overrides": [],
        },
    }


# 1. Model Performance Dashboard
model_perf = create_dashboard(
    "model-performance",
    "1. Model Performance",
    [
        timeseries_panel(
            "Prediction Throughput",
            0,
            0,
            [{"expr": "sum(rate(ml_predictions_total[5m]))", "legend": "requests/sec"}],
            unit="reqps",
        ),
        timeseries_panel(
            "Prediction Latency",
            12,
            0,
            [
                {
                    "expr": "histogram_quantile(0.50, sum(rate(ml_prediction_duration_seconds_bucket[5m])) by (le))",
                    "legend": "P50",
                },
                {
                    "expr": "histogram_quantile(0.95, sum(rate(ml_prediction_duration_seconds_bucket[5m])) by (le))",
                    "legend": "P95",
                },
                {
                    "expr": "histogram_quantile(0.99, sum(rate(ml_prediction_duration_seconds_bucket[5m])) by (le))",
                    "legend": "P99",
                },
            ],
            unit="s",
        ),
        {
            "type": "piechart",
            "title": "Success vs Error",
            "gridPos": {"x": 0, "y": 8, "w": 8, "h": 8},
            "targets": [
                {
                    "expr": 'sum(increase(ml_predictions_total{status="success"}[$__range])) or vector(0)',
                    "legendFormat": "Success",
                },
                {
                    "expr": 'sum(increase(ml_predictions_total{status="error"}[$__range])) or vector(0)',
                    "legendFormat": "Error",
                },
            ],
            "options": {
                "reduceOptions": {"calcs": ["lastNotNull"]},
                "pieType": "pie",
                "tooltip": {"mode": "single", "sort": "none"},
            },
        },
        stat_panel("Models Loaded", 8, 8, "sum(ml_model_loads_total)"),
    ],
)

# 2. Feature Store Dashboard
feature_store = create_dashboard(
    "feature-store",
    "2. Feature Store",
    [
        stat_panel(
            "Cache Hit Rate",
            0,
            0,
            "(sum(rate(ml_pipeline_feature_cache_hits_total[5m])) / (sum(rate(ml_pipeline_feature_cache_hits_total[5m])) + sum(rate(ml_pipeline_feature_cache_misses_total[5m])))) * 100",
            unit="percent",
            decimals=2,
            thresholds={
                "mode": "absolute",
                "steps": [
                    {"color": "red", "value": None},
                    {"color": "orange", "value": 50},
                    {"color": "green", "value": 80},
                ],
            },
        ),
        stat_panel(
            "Total Entities",
            6,
            0,
            "sum(ml_pipeline_feature_store_entities_total)",
        ),
        stat_panel(
            "Total Features",
            12,
            0,
            "sum(ml_pipeline_feature_store_features_total)",
        ),
        stat_panel(
            "Ingestion Rate",
            18,
            0,
            'sum(rate(ml_pipeline_feature_ingestion_total{status="success"}[5m]))',
            unit="ops",
            decimals=1,
        ),
        timeseries_panel(
            "Cache Hits vs Misses",
            0,
            6,
            [
                {"expr": "sum(rate(ml_pipeline_feature_cache_hits_total[5m]))", "legend": "Hits"},
                {
                    "expr": "sum(rate(ml_pipeline_feature_cache_misses_total[5m]))",
                    "legend": "Misses",
                },
            ],
        ),
        timeseries_panel(
            "Feature Ingestion Throughput",
            12,
            6,
            [
                {
                    "expr": 'sum(rate(ml_pipeline_feature_ingestion_total{method="put"}[5m])) by (feature_group)',
                    "legend": "put {{feature_group}}",
                },
                {
                    "expr": 'sum(rate(ml_pipeline_feature_ingestion_total{method="bulk_put"}[5m])) by (feature_group)',
                    "legend": "bulk_put {{feature_group}}",
                },
            ],
            unit="ops",
        ),
        timeseries_panel(
            "Ingestion Latency (P95)",
            0,
            14,
            [
                {
                    "expr": "histogram_quantile(0.95, sum(rate(ml_pipeline_feature_ingestion_duration_seconds_bucket[5m])) by (le, feature_group))",
                    "legend": "{{feature_group}}",
                },
            ],
            unit="s",
        ),
        timeseries_panel(
            "Entities per Feature Group",
            12,
            14,
            [
                {
                    "expr": "ml_pipeline_feature_store_entities_total",
                    "legend": "{{feature_group}}",
                },
            ],
        ),
    ],
)

# 3. System Resources Dashboard
system_resources = create_dashboard(
    "system-resources",
    "3. System Resources",
    [
        timeseries_panel(
            "Redis Memory (MB)",
            0,
            0,
            [
                {
                    "expr": "redis_memory_used_bytes / 1024 / 1024",
                    "legend": "Memory Used",
                }
            ],
        ),
        timeseries_panel(
            "Redis Connections",
            12,
            0,
            [{"expr": "redis_connected_clients", "legend": "Clients"}],
        ),
        timeseries_panel(
            "Postgres Connections",
            0,
            8,
            [{"expr": 'pg_stat_database_numbackends{datname!~"template.*"}', "legend": "{{datname}}"}],
        ),
        timeseries_panel(
            "Postgres DB Size (MB)",
            12,
            8,
            [{"expr": 'pg_database_size_bytes{datname!~"template.*"} / 1024 / 1024', "legend": "{{datname}}"}],
        ),
    ],
)

# 4. Error Tracking Dashboard (was 5, Data Ingestion removed)
error_tracking = create_dashboard(
    "error-tracking",
    "5. Error Tracking",
    [
        timeseries_panel(
            "Error Rate Trend",
            0,
            0,
            [
                {
                    "expr": 'sum(rate(ml_predictions_total{status="error"}[5m]))',
                    "legend": "Prediction Errors",
                },
                {
                    "expr": 'sum(rate(ml_batch_predictions_total{status="error"}[5m]))',
                    "legend": "Batch Prediction Errors",
                },
                {
                    "expr": 'sum(rate(ml_model_loads_total{status="error"}[5m]))',
                    "legend": "Model Load Errors",
                },
                {
                    "expr": 'sum(rate(ml_api_requests_total{status=~"5.."}[5m]))',
                    "legend": "HTTP 5xx Errors",
                },
            ],
            w=24,
        )
    ],
)

# 6. Applications Uptime (Custom)
apps_uptime = create_dashboard(
    "apps-uptime",
    "Applications Uptime & Health",
    [
        # Service Health Status (0/1 over time)
        {
            "type": "timeseries",
            "title": "Service Health Status",
            "gridPos": {"x": 0, "y": 0, "w": 24, "h": 8},
            "targets": [
                {
                    "expr": 'max(up{job="ml-pipeline-api-service"}) or vector(0)',
                    "legendFormat": "API",
                    "refId": "A",
                },
                {
                    "expr": '(max(ml_dependency_health{dependency="mlflow"}) or vector(0)) * on() group_left() (max(up{job="ml-pipeline-api-service"}) or vector(0))',
                    "legendFormat": "MLflow",
                    "refId": "B",
                },
                {
                    "expr": '(max(ml_dependency_health{dependency="redis"}) or vector(0)) * on() group_left() (max(up{job="ml-pipeline-api-service"}) or vector(0))',
                    "legendFormat": "Redis",
                    "refId": "C",
                },
            ],
            "options": {"legend": {"displayMode": "list", "placement": "bottom"}},
            "fieldConfig": {
                "defaults": {
                    "min": 0,
                    "max": 1,
                    "decimals": 0,
                    "custom": {
                        "drawStyle": "line",
                        "lineInterpolation": "stepAfter",
                        "lineWidth": 2,
                        "fillOpacity": 20,
                        "showPoints": "never",
                    },
                    "thresholds": {
                        "mode": "absolute",
                        "steps": [
                            {"color": "red", "value": None},
                            {"color": "green", "value": 1},
                        ],
                    },
                    "color": {"mode": "thresholds"},
                },
                "overrides": [],
            },
        },
        # API Uptime %
        stat_panel(
            "API Uptime (24h%)",
            0,
            8,
            'avg_over_time(up{job="ml-pipeline-api-service"}[24h]) * 100',
            unit="percent",
            decimals=2,
            thresholds={
                "mode": "absolute",
                "steps": [
                    {"color": "red", "value": None},
                    {"color": "orange", "value": 90},
                    {"color": "green", "value": 99},
                ],
            },
        ),
        # Time since boot
        stat_panel(
            "API Time Since Boot",
            6,
            8,
            'time() - process_start_time_seconds{job="ml-pipeline-api-service"}',
            unit="s",
        ),
    ],
)

dashboards = {
    "model-performance.json": model_perf,
    "feature-store.json": feature_store,
    "system-resources.json": system_resources,
    "error-tracking.json": error_tracking,
    "apps-uptime.json": apps_uptime,
}

for filename, data in dashboards.items():
    with open(os.path.join(DASHBOARDS_DIR, filename), "w") as f:
        json.dump(data, f, indent=2)

print(f"Generated {len(dashboards)} dashboards to {DASHBOARDS_DIR}/")
