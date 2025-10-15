#!/bin/bash
# Test all Prometheus queries from documentation using curl
# Based on: docs/monitoring/prometheus-monitoring.md

PROMETHEUS_URL="${PROMETHEUS_URL:-http://localhost:9090}"
BOLD='\033[1m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Helper function to execute Prometheus query
query_prometheus() {
    local query="$1"
    local description="$2"

    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}Query:${NC} ${description}"
    echo -e "${YELLOW}PromQL:${NC} ${query}"
    echo ""

    # URL encode the query
    local encoded_query=$(echo -n "$query" | python -c "import sys; from urllib.parse import quote; print(quote(sys.stdin.read()))" 2>/dev/null || echo -n "$query" | sed 's/ /%20/g')

    # Execute query
    local response=$(curl -s "${PROMETHEUS_URL}/api/v1/query?query=${encoded_query}")

    # Parse and display result
    if echo "$response" | grep -q '"status":"success"'; then
        echo -e "${GREEN}✓ Success${NC}"
        echo "$response" | python -c "
import sys, json
try:
    data = json.load(sys.stdin)
    result = data.get('data', {}).get('result', [])
    if result:
        print('\nResult:')
        for item in result[:10]:  # Limit to first 10 results
            metric = item.get('metric', {})
            value = item.get('value', ['', 'N/A'])
            metric_str = ', '.join([f'{k}={v}' for k, v in metric.items()])
            if metric_str:
                print(f'  {metric_str} = {value[1]}')
            else:
                print(f'  Value: {value[1]}')
        if len(result) > 10:
            print(f'  ... and {len(result) - 10} more results')
    else:
        print('\nNo data returned')
except Exception as e:
    print(f'Error parsing: {e}', file=sys.stderr)
" 2>/dev/null || echo "$response"
    else
        echo -e "${YELLOW}⚠ Warning: Query returned no success status${NC}"
        echo "$response" | head -5
    fi
    echo ""
}

echo -e "${BOLD}${BLUE}"
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║       PROMETHEUS QUERY TEST SUITE                                ║"
echo "║       Testing all queries from documentation                     ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# =============================================================================
# SERVICE HEALTH CHECKS
# =============================================================================
echo -e "${BOLD}${BLUE}[1] SERVICE HEALTH CHECKS${NC}"
echo ""

query_prometheus \
    'up{job=~"model-api|redis|postgres|redpanda|prometheus"}' \
    "Check all services are UP (should be 1)"

query_prometheus \
    'up{job="model-api"}' \
    "Model API service health"

query_prometheus \
    'min(up{job=~"model-api|redis|postgres"})' \
    "Minimum service availability (0 = at least one service down)"

# =============================================================================
# PREDICTION METRICS
# =============================================================================
echo -e "${BOLD}${BLUE}[2] PREDICTION METRICS${NC}"
echo ""

query_prometheus \
    'sum(ml_predictions_total)' \
    "Total predictions made (all time)"

query_prometheus \
    'sum(rate(ml_predictions_total[5m]))' \
    "Prediction rate (requests per second)"

query_prometheus \
    'sum by (status) (ml_predictions_total)' \
    "Predictions breakdown by status"

query_prometheus \
    'sum by (model_version) (ml_predictions_total)' \
    "Predictions by model version"

query_prometheus \
    'sum(increase(ml_predictions_total[1h]))' \
    "Total predictions in last hour"

query_prometheus \
    'sum(increase(ml_predictions_total[24h]))' \
    "Total predictions in last 24 hours"

query_prometheus \
    '(sum(rate(ml_predictions_total{status="success"}[5m])) / sum(rate(ml_predictions_total[5m]))) * 100' \
    "Success rate percentage"

query_prometheus \
    '(sum(rate(ml_predictions_total{status="error"}[5m])) / sum(rate(ml_predictions_total[5m]))) * 100' \
    "Error rate percentage"

query_prometheus \
    'sum(ml_predictions_total{status="cache_hit"}) / sum(ml_predictions_total)' \
    "Cache hit rate (application level)"

# =============================================================================
# LATENCY METRICS
# =============================================================================
echo -e "${BOLD}${BLUE}[3] LATENCY METRICS${NC}"
echo ""

query_prometheus \
    'histogram_quantile(0.50, rate(ml_prediction_duration_seconds_bucket[5m]))' \
    "P50 (Median) latency in seconds"

query_prometheus \
    'histogram_quantile(0.95, rate(ml_prediction_duration_seconds_bucket[5m]))' \
    "P95 latency in seconds"

query_prometheus \
    'histogram_quantile(0.99, rate(ml_prediction_duration_seconds_bucket[5m]))' \
    "P99 latency in seconds"

query_prometheus \
    'rate(ml_prediction_duration_seconds_sum[5m]) / rate(ml_prediction_duration_seconds_count[5m])' \
    "Average prediction latency in seconds"

query_prometheus \
    'sum(ml_prediction_duration_seconds_sum)' \
    "Total time spent on predictions (seconds)"

query_prometheus \
    'histogram_quantile(0.95, sum by (model_version, le) (rate(ml_prediction_duration_seconds_bucket[5m])))' \
    "P95 latency by model version"

# =============================================================================
# MODEL LOADING METRICS
# =============================================================================
echo -e "${BOLD}${BLUE}[4] MODEL LOADING METRICS${NC}"
echo ""

query_prometheus \
    'sum(ml_model_loads_total)' \
    "Total model loads"

query_prometheus \
    'sum by (model_version) (ml_model_loads_total)' \
    "Model loads by version"

query_prometheus \
    'sum(ml_model_loads_total{status="error"})' \
    "Failed model loads"

query_prometheus \
    'sum(rate(ml_model_loads_total{status="success"}[5m])) / sum(rate(ml_model_loads_total[5m]))' \
    "Model load success rate"

# =============================================================================
# REDIS CACHE METRICS
# =============================================================================
echo -e "${BOLD}${BLUE}[5] REDIS CACHE METRICS${NC}"
echo ""

query_prometheus \
    'rate(redis_keyspace_hits_total[5m]) / (rate(redis_keyspace_hits_total[5m]) + rate(redis_keyspace_misses_total[5m]))' \
    "Redis cache hit rate"

query_prometheus \
    'sum(redis_keyspace_hits_total)' \
    "Total Redis cache hits"

query_prometheus \
    'rate(redis_keyspace_misses_total[5m])' \
    "Redis cache miss rate"

query_prometheus \
    'redis_memory_used_bytes / 1024 / 1024' \
    "Redis memory usage in MB"

query_prometheus \
    'redis_connected_clients' \
    "Redis connected clients"

# =============================================================================
# POSTGRESQL METRICS
# =============================================================================
echo -e "${BOLD}${BLUE}[6] POSTGRESQL DATABASE METRICS${NC}"
echo ""

query_prometheus \
    'pg_stat_database_numbackends{datname="mlflow"}' \
    "Active connections to MLflow database"

query_prometheus \
    'sum(pg_stat_database_numbackends)' \
    "Total database connections (all databases)"

query_prometheus \
    'sum by (datname) (pg_stat_database_numbackends)' \
    "Connections by database"

query_prometheus \
    'pg_database_size_bytes{datname="mlflow"} / 1024 / 1024 / 1024' \
    "MLflow database size in GB"

query_prometheus \
    'pg_up' \
    "PostgreSQL availability (1 = up)"

# =============================================================================
# PYTHON APPLICATION METRICS
# =============================================================================
echo -e "${BOLD}${BLUE}[7] PYTHON APPLICATION METRICS${NC}"
echo ""

query_prometheus \
    'process_resident_memory_bytes / 1024 / 1024' \
    "API memory usage in MB"

query_prometheus \
    'rate(process_cpu_seconds_total[5m])' \
    "API CPU usage rate"

query_prometheus \
    'rate(python_gc_collections_total[5m])' \
    "Garbage collection rate by generation"

query_prometheus \
    'process_open_fds' \
    "Open file descriptors"

# =============================================================================
# CAPACITY PLANNING QUERIES
# =============================================================================
echo -e "${BOLD}${BLUE}[8] CAPACITY PLANNING${NC}"
echo ""

query_prometheus \
    'sum by (model_name) (rate(ml_predictions_total[1m])) * 60' \
    "Predictions per minute by model"

query_prometheus \
    'sum by (model_version) (rate(ml_predictions_total[5m]))' \
    "Predictions per second by version"

query_prometheus \
    'max_over_time(sum(rate(ml_predictions_total[1m]))[1h:1m])' \
    "Peak request rate in last hour"

query_prometheus \
    'avg_over_time(process_resident_memory_bytes[1h]) / 1024 / 1024' \
    "Average memory usage over last hour (MB)"

query_prometheus \
    'avg_over_time(pg_stat_database_numbackends{datname="mlflow"}[1h])' \
    "Average database connections over last hour"

# =============================================================================
# SLI/SLO MONITORING
# =============================================================================
echo -e "${BOLD}${BLUE}[9] SLI/SLO MONITORING${NC}"
echo ""

query_prometheus \
    'histogram_quantile(0.95, rate(ml_prediction_duration_seconds_bucket[5m])) < 0.1' \
    "SLI: 95% of requests < 100ms (boolean)"

query_prometheus \
    'histogram_quantile(0.99, rate(ml_prediction_duration_seconds_bucket[5m])) < 0.5' \
    "SLI: 99% of requests < 500ms (boolean)"

query_prometheus \
    '(sum(rate(ml_predictions_total{status="success"}[5m])) / sum(rate(ml_predictions_total[5m]))) > 0.999' \
    "SLO: 99.9% availability (boolean)"

query_prometheus \
    '(1 - (sum(rate(ml_predictions_total{status="success"}[1h])) / sum(rate(ml_predictions_total[1h]))))' \
    "Error budget burn rate"

# =============================================================================
# APDEX SCORE
# =============================================================================
echo -e "${BOLD}${BLUE}[10] APDEX SCORE (Application Performance Index)${NC}"
echo ""

query_prometheus \
    '(sum(rate(ml_prediction_duration_seconds_bucket{le="0.1"}[5m])) + (sum(rate(ml_prediction_duration_seconds_bucket{le="0.5"}[5m])) - sum(rate(ml_prediction_duration_seconds_bucket{le="0.1"}[5m]))) / 2) / sum(rate(ml_prediction_duration_seconds_count[5m]))' \
    "Apdex score (target: 100ms, tolerable: 500ms)"

# =============================================================================
# SUMMARY
# =============================================================================
echo -e "${BOLD}${BLUE}"
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║       TEST SUITE COMPLETED                                       ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

echo ""
echo "Prometheus URL: ${PROMETHEUS_URL}"
echo "Grafana URL: http://localhost:3001 (admin/admin123)"
echo "Model API: http://localhost:8000"
echo ""
echo "To generate more traffic: bash scripts/generate_monitoring_traffic.sh"
echo "To view documentation: cat docs/monitoring/QUICK_START.md"
echo ""
