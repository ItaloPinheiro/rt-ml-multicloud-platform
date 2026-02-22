import yaml
import os

from textwrap import dedent

RULES_DIR = "ops/monitoring/prometheus/rules"
ALERTS_DIR = "ops/monitoring/prometheus/alerts"
os.makedirs(RULES_DIR, exist_ok=True)
os.makedirs(ALERTS_DIR, exist_ok=True)

# 1. Scrape Configuration (K8s / AWS demo)
# - No alertmanager block (not deployed in K8s)
# - metrics_path uses trailing slash for FastAPI ASGI mount compatibility
# - redis/postgres targets point to exporter sidecars, not native service ports
prometheus_yml = {
    "global": {
        "scrape_interval": "5s",
        "evaluation_interval": "5s"
    },
    "rule_files": [
        "alert_rules.yml",
        "recording_rules.yml"
    ],
    "scrape_configs": [
        {
            "job_name": "prometheus",
            "static_configs": [{"targets": ["localhost:9090"]}]
        },
        {
            "job_name": "ml-pipeline-api-service",
            "scrape_interval": "5s",
            "metrics_path": "/metrics/",
            "static_configs": [{"targets": ["ml-pipeline-api-service:8000"]}]
        },
        {
            "job_name": "redis",
            "static_configs": [{"targets": ["redis-exporter:9121"]}]
        },
        {
            "job_name": "postgres",
            "static_configs": [{"targets": ["postgres-exporter:9187"]}]
        },
        {
            "job_name": "kubernetes-apiservers",
            "kubernetes_sd_configs": [{"role": "endpoints"}],
            "scheme": "https",
            "tls_config": {"ca_file": "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"},
            "bearer_token_file": "/var/run/secrets/kubernetes.io/serviceaccount/token",
            "relabel_configs": [
                {
                    "source_labels": ["__meta_kubernetes_namespace", "__meta_kubernetes_service_name", "__meta_kubernetes_endpoint_port_name"],
                    "action": "keep",
                    "regex": "default;kubernetes;https"
                }
            ]
        },
        {
            "job_name": "kubernetes-nodes",
            "kubernetes_sd_configs": [{"role": "node"}],
            "scheme": "https",
            "tls_config": {"ca_file": "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"},
            "bearer_token_file": "/var/run/secrets/kubernetes.io/serviceaccount/token"
        }
    ]
}

# 2. Alert Rules
alert_rules_yml = {
    "groups": [
        {
            "name": "ml_pipeline_alerts",
            "interval": "30s",
            "rules": [
                {
                    "alert": "HighErrorRate",
                    "expr": '(sum(rate(ml_predictions_total{status="error"}[5m])) / sum(rate(ml_predictions_total[5m]))) > 0.05',
                    "for": "5m",
                    "labels": {"severity": "warning"},
                    "annotations": {
                        "summary": "High error rate detected",
                        "description": "Error rate is above 5% over the last 5 minutes"
                    }
                },
                {
                    "alert": "HighPredictionLatency",
                    "expr": 'histogram_quantile(0.95, rate(ml_prediction_duration_seconds_bucket[5m])) > 0.5',
                    "for": "5m",
                    "labels": {"severity": "warning"},
                    "annotations": {
                        "summary": "High prediction latency",
                        "description": "95th percentile latency is {{ $value }}s"
                    }
                },
                 {
                    "alert": "CriticalPredictionLatency",
                    "expr": 'histogram_quantile(0.95, rate(ml_prediction_duration_seconds_bucket[5m])) > 1.0',
                    "for": "2m",
                    "labels": {"severity": "critical"},
                    "annotations": {
                        "summary": "Critical prediction latency",
                        "description": "95th percentile latency is {{ $value }}s (threshold: 1s)"
                    }
                },
                {
                    "alert": "ModelAPIDown",
                    "expr": 'up{job="ml-pipeline-api-service"} == 0',
                    "for": "1m",
                    "labels": {"severity": "critical"},
                    "annotations": {
                        "summary": "Model API service is down",
                        "description": "The ML Model API has been down for more than 1 minute"
                    }
                },
                 {
                    "alert": "LowCacheHitRate",
                    "expr": '(rate(redis_keyspace_hits_total[5m]) / (rate(redis_keyspace_hits_total[5m]) + rate(redis_keyspace_misses_total[5m]))) < 0.5',
                    "for": "10m",
                    "labels": {"severity": "warning"},
                    "annotations": {
                        "summary": "Low Redis cache hit rate",
                        "description": "Cache hit rate is {{ $value }}"
                    }
                },
                 {
                    "alert": "NoPredictions",
                    "expr": 'rate(ml_predictions_total[5m]) == 0',
                    "for": "10m",
                    "labels": {"severity": "warning"},
                    "annotations": {
                        "summary": "No predictions being made",
                        "description": "The API hasn't received any prediction requests in the last 10 minutes"
                    }
                }
            ]
        }
    ]
}

# 3. Recording Rules
recording_rules_yml = {
    "groups": [
        {
            "name": "ml_pipeline_recording_rules",
            "interval": "30s",
            "rules": [
                {
                    "record": "job:prediction_success_rate:5m",
                    "expr": 'sum by (model_name) (rate(ml_predictions_total{status="success"}[5m])) / sum by (model_name) (rate(ml_predictions_total[5m]))'
                },
                {
                    "record": "job:prediction_latency_p95:5m",
                    "expr": 'histogram_quantile(0.95, sum by (model_name, le) (rate(ml_prediction_duration_seconds_bucket[5m])))'
                },
                {
                    "record": "job:prediction_latency_p99:5m",
                    "expr": 'histogram_quantile(0.99, sum by (model_name, le) (rate(ml_prediction_duration_seconds_bucket[5m])))'
                },
                {
                    "record": "job:prediction_throughput:1m",
                    "expr": 'sum(rate(ml_predictions_total[1m])) * 60'
                },
                {
                    "record": "job:cache_hit_rate:5m",
                    "expr": 'sum(ml_predictions_total{status="cache_hit"}) / sum(ml_predictions_total)'
                }
            ]
        }
    ]
}

# 4. Grafana Datasource Configuration
datasource_yml = {
    "apiVersion": 1,
    "datasources": [
        {
            "name": "Prometheus",
            "type": "prometheus",
            "access": "proxy",
            "url": "${PROMETHEUS_URL}",
            "isDefault": True,
            "jsonData": {
                "httpMethod": "POST",
                "manageAlerts": True
            }
        }
    ]
}

dashboard_provider_yml = {
    "apiVersion": 1,
    "providers": [
        {
            "name": "default",
            "orgId": 1,
            "folder": "",
            "type": "file",
            "disableDeletion": False,
            "updateIntervalSeconds": 10,
            "options": {
                "path": "/var/lib/grafana/dashboards"
            }
        }
    ]
}

with open("ops/monitoring/prometheus/prometheus.yml", "w") as f:
    yaml.dump(prometheus_yml, f, default_flow_style=False, sort_keys=False)

# 5. Generate Local Prometheus Configuration (override for Docker Compose)
# Local uses docker-compose service names and includes redpanda
prometheus_local_yml = prometheus_yml.copy()
prometheus_local_yml["scrape_configs"] = [
    {
        "job_name": "prometheus",
        "static_configs": [{"targets": ["localhost:9090"]}]
    },
    {
        "job_name": "ml-pipeline-api-service",
        "scrape_interval": "5s",
        "metrics_path": "/metrics/",
        "static_configs": [{"targets": ["ml-pipeline-api-service:8000"]}]
    },
    {
        "job_name": "redis",
        "static_configs": [{"targets": ["redis-exporter:9121"]}]
    },
    {
        "job_name": "postgres",
        "static_configs": [{"targets": ["postgres-exporter:9187"]}]
    },
    {
        "job_name": "redpanda",
        "static_configs": [{"targets": ["redpanda:9644"]}]
    }
]

with open("ops/monitoring/prometheus/prometheus-local.yml", "w") as f:
    yaml.dump(prometheus_local_yml, f, default_flow_style=False, sort_keys=False)

with open("ops/monitoring/prometheus/alerts/alert_rules.yml", "w") as f:
    yaml.dump(alert_rules_yml, f, default_flow_style=False, sort_keys=False)

with open("ops/monitoring/prometheus/rules/recording_rules.yml", "w") as f:
    yaml.dump(recording_rules_yml, f, default_flow_style=False, sort_keys=False)

with open("ops/monitoring/grafana/datasources/datasources.yaml", "w") as f:
    yaml.dump(datasource_yml, f, default_flow_style=False, sort_keys=False)

with open("ops/monitoring/grafana/dashboards/dashboards.yaml", "w") as f:
    yaml.dump(dashboard_provider_yml, f, default_flow_style=False, sort_keys=False)

print("Generated Prometheus and Grafana configuration files successfully.")
