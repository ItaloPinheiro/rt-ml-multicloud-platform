#!/usr/bin/env bash
# Load test script for the ML Pipeline API
# Generates prediction traffic to populate Grafana dashboards (latency, cache hits/misses)
#
# Usage:
#   ./scripts/demo/demo-aws/load-test.sh                    # defaults: 100 requests, 10 concurrent
#   ./scripts/demo/demo-aws/load-test.sh --requests 500 --concurrency 20
#   ./scripts/demo/demo-aws/load-test.sh --entity-ids       # use Feature Store lookups (cache test)

set -euo pipefail

# Defaults
TOTAL_REQUESTS=100
CONCURRENCY=10
USE_ENTITY_IDS=false
API_URL="${API_URL:-}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --requests)       TOTAL_REQUESTS="$2"; shift 2 ;;
        --concurrency)    CONCURRENCY="$2"; shift 2 ;;
        --entity-ids)     USE_ENTITY_IDS=true; shift ;;
        --api-url)        API_URL="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [--requests N] [--concurrency N] [--entity-ids] [--api-url URL]"
            echo ""
            echo "Options:"
            echo "  --requests N      Total number of requests (default: 100)"
            echo "  --concurrency N   Parallel workers (default: 10)"
            echo "  --entity-ids      Use Feature Store entity_id lookups (tests Redis cache)"
            echo "  --api-url URL     API base URL (default: auto-detect from AWS)"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Auto-detect API URL if not set
if [ -z "$API_URL" ]; then
    if [ -n "${INSTANCE_IP:-}" ]; then
        API_URL="http://${INSTANCE_IP}:30800"
    else
        INSTANCE_IP=$(aws ec2 describe-instances \
            --filters "Name=tag:Name,Values=rt-ml-platform-demo-instance" "Name=instance-state-name,Values=running" \
            --query "Reservations[*].Instances[*].PublicIpAddress" \
            --output text 2>/dev/null || true)
        if [ -z "$INSTANCE_IP" ]; then
            echo "ERROR: Could not detect instance IP. Set API_URL or INSTANCE_IP."
            exit 1
        fi
        API_URL="http://${INSTANCE_IP}:30800"
    fi
fi

echo "=== ML Pipeline Load Test ==="
echo "API:         $API_URL"
echo "Requests:    $TOTAL_REQUESTS"
echo "Concurrency: $CONCURRENCY"
echo "Mode:        $([ "$USE_ENTITY_IDS" = true ] && echo 'Feature Store (entity_id)' || echo 'Explicit features')"
echo ""

# Health check
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/health" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" != "200" ]; then
    echo "ERROR: API not reachable at $API_URL (HTTP $HTTP_CODE)"
    exit 1
fi
echo "API is healthy."

# Fetch entity IDs if needed
ENTITY_IDS=()
if [ "$USE_ENTITY_IDS" = true ]; then
    echo "Fetching entity IDs from Feature Store..."
    ENTITY_IDS_RAW=$(curl -s "$API_URL/features/groups" | python3 -c "
import sys, json
groups = json.load(sys.stdin)
if not groups:
    sys.exit(1)
" 2>/dev/null && \
    ssh -i ~/.ssh/rt-ml-platform-aws-ec2.pem "ubuntu@${INSTANCE_IP}" \
        "sudo k3s kubectl exec deployment/postgres -n ml-pipeline -- psql -U mlflow -d mlflow -t -A -c \
        'SELECT entity_id FROM feature_store WHERE feature_group = '\''transaction_features'\'' ORDER BY RANDOM() LIMIT 50'" 2>/dev/null || true)

    if [ -z "$ENTITY_IDS_RAW" ]; then
        echo "WARNING: Could not fetch entity IDs. Falling back to explicit features."
        USE_ENTITY_IDS=false
    else
        IFS=$'\n' read -r -d '' -a ENTITY_IDS <<< "$ENTITY_IDS_RAW" || true
        echo "Loaded ${#ENTITY_IDS[@]} entity IDs."
    fi
fi

# Prepare payloads
LEGITIMATE='{"features":{"hour_of_day":10,"day_of_week":2,"is_weekend":0,"transaction_count_24h":2,"avg_amount_30d":75.0,"amount":42.50,"merchant_category_encoded":75,"payment_method_encoded":5},"model_name":"fraud_detector","return_probabilities":true}'
FRAUD='{"features":{"hour_of_day":3,"day_of_week":5,"is_weekend":1,"transaction_count_24h":1,"avg_amount_30d":3500.0,"amount":4850.0,"merchant_category_encoded":63,"payment_method_encoded":5},"model_name":"fraud_detector","return_probabilities":true}'

# Create temp dir for results
RESULTS_DIR=$(mktemp -d)
trap "rm -rf $RESULTS_DIR" EXIT

# Worker function
make_request() {
    local id=$1
    local payload

    if [ "$USE_ENTITY_IDS" = true ] && [ ${#ENTITY_IDS[@]} -gt 0 ]; then
        local idx=$((id % ${#ENTITY_IDS[@]}))
        local eid="${ENTITY_IDS[$idx]}"
        payload="{\"entity_id\":\"$eid\",\"model_name\":\"fraud_detector\",\"return_probabilities\":true}"
    else
        if (( id % 3 == 0 )); then
            payload="$FRAUD"
        else
            payload="$LEGITIMATE"
        fi
    fi

    local start_ms
    start_ms=$(date +%s%3N 2>/dev/null || python3 -c "import time; print(int(time.time()*1000))")

    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API_URL/predict" \
        -H "Content-Type: application/json" \
        -d "$payload" --max-time 10 2>/dev/null || echo "000")

    local end_ms
    end_ms=$(date +%s%3N 2>/dev/null || python3 -c "import time; print(int(time.time()*1000))")

    local latency=$((end_ms - start_ms))
    echo "$latency $http_code" > "$RESULTS_DIR/$id.txt"
}

# Run load test
echo ""
echo "Running $TOTAL_REQUESTS requests with $CONCURRENCY workers..."
echo ""

STARTED=0
ACTIVE=0
START_TIME=$(date +%s%3N 2>/dev/null || python3 -c "import time; print(int(time.time()*1000))")

for ((i=0; i<TOTAL_REQUESTS; i++)); do
    make_request "$i" &
    ACTIVE=$((ACTIVE + 1))

    if [ "$ACTIVE" -ge "$CONCURRENCY" ]; then
        wait -n 2>/dev/null || wait
        ACTIVE=$((ACTIVE - 1))
    fi

    # Progress every 25%
    PROGRESS=$(( (i + 1) * 100 / TOTAL_REQUESTS ))
    if (( (i + 1) % (TOTAL_REQUESTS / 4 + 1) == 0 )); then
        echo "  Progress: $((i + 1))/$TOTAL_REQUESTS ($PROGRESS%)"
    fi
done

wait

END_TIME=$(date +%s%3N 2>/dev/null || python3 -c "import time; print(int(time.time()*1000))")
TOTAL_MS=$((END_TIME - START_TIME))

# Collect results
LATENCIES=()
ERRORS=0
SUCCESS=0

for ((i=0; i<TOTAL_REQUESTS; i++)); do
    if [ -f "$RESULTS_DIR/$i.txt" ]; then
        read -r lat code < "$RESULTS_DIR/$i.txt"
        LATENCIES+=("$lat")
        if [ "$code" = "200" ]; then
            SUCCESS=$((SUCCESS + 1))
        else
            ERRORS=$((ERRORS + 1))
        fi
    else
        ERRORS=$((ERRORS + 1))
    fi
done

# Calculate percentiles
IFS=$'\n' SORTED=($(printf '%s\n' "${LATENCIES[@]}" | sort -n)); unset IFS
N=${#SORTED[@]}

if [ "$N" -gt 0 ]; then
    SUM=0
    for lat in "${SORTED[@]}"; do SUM=$((SUM + lat)); done
    AVG=$((SUM / N))
    P50=${SORTED[$((N * 50 / 100))]}
    P95=${SORTED[$((N * 95 / 100))]}
    P99=${SORTED[$((N * 99 / 100))]}
    MIN=${SORTED[0]}
    MAX=${SORTED[$((N - 1))]}

    echo ""
    echo "=== Results ==="
    echo "Total time:   ${TOTAL_MS}ms"
    echo "Throughput:   $(python3 -c "print(f'{$N / ($TOTAL_MS / 1000):.1f}')" 2>/dev/null || echo "N/A") req/s"
    echo ""
    echo "Latency:"
    echo "  Min:  ${MIN}ms"
    echo "  Avg:  ${AVG}ms"
    echo "  P50:  ${P50}ms"
    echo "  P95:  ${P95}ms"
    echo "  P99:  ${P99}ms"
    echo "  Max:  ${MAX}ms"
    echo ""
    echo "Status:"
    echo "  Success: $SUCCESS"
    echo "  Errors:  $ERRORS"
    echo "  Rate:    $(python3 -c "print(f'{$SUCCESS / $N * 100:.1f}')" 2>/dev/null || echo "N/A")%"
else
    echo ""
    echo "ERROR: No results collected"
fi
