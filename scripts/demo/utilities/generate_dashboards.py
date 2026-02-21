import json
import os

from textwrap import dedent

DASHBOARDS_DIR = "ops/monitoring/grafana/dashboards"
os.makedirs(DASHBOARDS_DIR, exist_ok=True)

def create_dashboard(uid, title, panels):
    return {
        "uid": uid,
        "title": title,
        "panels": panels,
        "schemaVersion": 36,
        "timezone": "browser",
        "refresh": "1m"
    }

def stat_panel(title, x, y, expr, mappings=None, thresholds=None, unit="none", decimals=0):
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
                "thresholds": thresholds
            },
            "overrides": []
        }
    }

def timeseries_panel(title, x, y, targets, unit="short", w=12, h=8):
    return {
        "type": "timeseries",
        "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [{"expr": t["expr"], "legendFormat": t.get("legend", ""), "refId": chr(65+i)} for i, t in enumerate(targets)],
        "options": {
            "legend": {"displayMode": "list", "placement": "bottom"}
        },
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "custom": {"drawStyle": "line", "lineInterpolation": "linear", "lineWidth": 1, "fillOpacity": 10}
            },
            "overrides": []
        }
    }


# 1. Model Performance Dashboard
model_perf = create_dashboard(
    "model-performance", "1. Model Performance",
    [
        timeseries_panel("Prediction Throughput", 0, 0, [{"expr": 'sum(rate(ml_predictions_total[5m]))', "legend": "requests/sec"}], unit="reqps"),
        timeseries_panel("Prediction Latency", 12, 0, [
            {"expr": 'histogram_quantile(0.50, rate(ml_prediction_duration_seconds_bucket[5m]))', "legend": "P50"},
            {"expr": 'histogram_quantile(0.95, rate(ml_prediction_duration_seconds_bucket[5m]))', "legend": "P95"},
            {"expr": 'histogram_quantile(0.99, rate(ml_prediction_duration_seconds_bucket[5m]))', "legend": "P99"}
        ], unit="s"),
        {
            "type": "piechart",
            "title": "Success vs Error",
            "gridPos": {"x": 0, "y": 8, "w": 8, "h": 8},
            "targets": [
                {"expr": 'sum(rate(ml_predictions_total{status="success"}[5m]))', "legendFormat": "Success"},
                {"expr": 'sum(rate(ml_predictions_total{status="error"}[5m]))', "legendFormat": "Error"}
            ],
            "options": {"pieType": "pie", "tooltip": {"mode": "single", "sort": "none"}}
        },
        stat_panel("Models Loaded", 8, 8, 'sum(ml_model_loads_total)'),
    ]
)

# 2. Feature Store Dashboard
feature_store = create_dashboard(
    "feature-store", "2. Feature Store",
    [
        stat_panel("Cache Hit Rate", 0, 0, 
            '(rate(redis_keyspace_hits_total[5m]) / (rate(redis_keyspace_hits_total[5m]) + rate(redis_keyspace_misses_total[5m]))) * 100',
            unit="percent", decimals=2,
            thresholds={"mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "orange", "value": 50}, {"color": "green", "value": 80}]}
        ),
        timeseries_panel("Cache Hits vs Misses", 6, 0, [
            {"expr": 'sum(rate(redis_keyspace_hits_total[5m]))', "legend": "Hits"},
            {"expr": 'sum(rate(redis_keyspace_misses_total[5m]))', "legend": "Misses"}
        ], w=18)
    ]
)

# 3. System Resources Dashboard
system_resources = create_dashboard(
    "system-resources", "3. System Resources",
    [
        timeseries_panel("Redis Memory (MB)", 0, 0, [{"expr": 'redis_memory_used_bytes / 1024 / 1024', "legend": "Memory Used"}]),
        timeseries_panel("Redis Connections", 12, 0, [{"expr": 'redis_connected_clients', "legend": "Clients"}]),
        timeseries_panel("Postgres Connections", 0, 8, [{"expr": 'pg_stat_database_numbackends', "legend": "{{datname}}"}]),
        timeseries_panel("Postgres DB Size (MB)", 12, 8, [{"expr": 'pg_database_size_bytes / 1024 / 1024', "legend": "{{datname}}"}])
    ]
)

# 4. Data Ingestion Dashboard (Stub, waiting for Redpanda)
data_ingestion = create_dashboard(
    "data-ingestion", "4. Data Ingestion",
    [
        stat_panel("Redpanda Status", 0, 0, 'max(up{job="redpanda"})', 
            mappings=[{"type": "value", "options": {"1": {"text": "UP", "color": "green"}, "0": {"text": "DOWN", "color": "red"}}}]
        )
    ]
)

# 5. Error Tracking Dashboard
error_tracking = create_dashboard(
    "error-tracking", "5. Error Tracking",
    [
        timeseries_panel("Error Rate Trend", 0, 0, [{"expr": 'sum(rate(ml_predictions_total{status="error"}[5m]))', "legend": "Errors/sec"}], w=24)
    ]
)

# 6. Applications Uptime (Custom)
apps_uptime = create_dashboard(
    "apps-uptime", "Applications Uptime & Health",
    [
        # API Health (Red/Green Box)
        {
            "type": "stat",
            "title": "API Status",
            "gridPos": {"x": 0, "y": 0, "w": 6, "h": 6},
            "targets": [{"expr": 'max(up{job="model-api"})', "refId": "A"}],
            "options": {"colorMode": "background", "graphMode": "none"},
            "fieldConfig": {"defaults": {
                "mappings": [{"type": "value", "options": {"1": {"text": "Healthy", "color": "green"}, "0": {"text": "Down", "color": "red"}}}],
                "thresholds": {"mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "green", "value": 1}]}
            }, "overrides": []}
        },
        # MLflow Health (Red/Green Box)
         {
            "type": "stat",
            "title": "MLflow Status",
            "gridPos": {"x": 6, "y": 0, "w": 6, "h": 6},
            "targets": [{"expr": 'max(ml_dependency_health{dependency="mlflow"})', "refId": "A"}],
            "options": {"colorMode": "background", "graphMode": "none"},
            "fieldConfig": {"defaults": {
                "mappings": [{"type": "value", "options": {"1": {"text": "Healthy", "color": "green"}, "0": {"text": "Down", "color": "red"}}}],
                "thresholds": {"mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "green", "value": 1}]}
            }, "overrides": []}
        },
        # Redis Health (New)
         {
            "type": "stat",
            "title": "Redis Status",
            "gridPos": {"x": 12, "y": 0, "w": 6, "h": 6},
            "targets": [{"expr": 'max(ml_dependency_health{dependency="redis"})', "refId": "A"}],
            "options": {"colorMode": "background", "graphMode": "none"},
            "fieldConfig": {"defaults": {
                "mappings": [{"type": "value", "options": {"1": {"text": "Healthy", "color": "green"}, "0": {"text": "Down", "color": "red"}}}],
                "thresholds": {"mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "green", "value": 1}]}
            }, "overrides": []}
        },
        # API Uptime %
        stat_panel("API Uptime (24h%)", 0, 6, 'avg_over_time(up{job="model-api"}[24h]) * 100', unit="percent", decimals=2,
            thresholds={"mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "orange", "value": 90}, {"color": "green", "value": 99}]}),
        # Time since boot
        stat_panel("API Time Since Boot", 6, 6, 'time() - process_start_time_seconds{job="model-api"}', unit="s")
    ]
)

dashboards = {
    "model-performance.json": model_perf,
    "feature-store.json": feature_store,
    "system-resources.json": system_resources,
    "data-ingestion.json": data_ingestion,
    "error-tracking.json": error_tracking,
    "apps-uptime.json": apps_uptime
}

for filename, data in dashboards.items():
    with open(os.path.join(DASHBOARDS_DIR, filename), "w") as f:
        json.dump(data, f, indent=2)

print(f"Generated {len(dashboards)} dashboards to {DASHBOARDS_DIR}/")
