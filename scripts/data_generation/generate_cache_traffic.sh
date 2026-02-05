#!/bin/bash

# Script to generate traffic with cache hits for testing monitoring metrics
# This script makes repeated requests to trigger cache hits and sustained traffic

set -e

API_URL="${API_URL:-http://localhost:8000}"
MODEL_NAME="${MODEL_NAME:-fraud_detector}"

echo "Generating traffic with cache hits for SLI/SLO metrics..."
echo "API: $API_URL"
echo "Model: $MODEL_NAME"
echo ""

# Define a few sample requests that we'll repeat
SAMPLE_REQUESTS=(
    '{"model_name":"fraud_detector","features":{"amount":150.0,"merchant_category_encoded":73,"payment_method_encoded":4,"hour_of_day":23,"day_of_week":6,"is_weekend":1,"transaction_count_24h":5,"avg_amount_30d":231.04,"risk_score":0.3}}'
    '{"model_name":"fraud_detector","features":{"amount":2500.0,"merchant_category_encoded":5,"payment_method_encoded":3,"hour_of_day":22,"day_of_week":6,"is_weekend":1,"transaction_count_24h":15,"avg_amount_30d":450.75,"risk_score":0.85}}'
    '{"model_name":"fraud_detector","features":{"amount":500.0,"merchant_category_encoded":10,"payment_method_encoded":2,"hour_of_day":14,"day_of_week":3,"is_weekend":0,"transaction_count_24h":8,"avg_amount_30d":320.50,"risk_score":0.45}}'
)

echo "Phase 1: Initial requests (no cache hits)"
echo "=========================================="
for i in {1..3}; do
    REQUEST="${SAMPLE_REQUESTS[$i-1]}"
    echo -n "Request $i (new): "

    RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$API_URL/predict" \
        -H "Content-Type: application/json" \
        -d "$REQUEST")

    HTTP_CODE=$(echo "$RESPONSE" | tail -n1)

    if [ "$HTTP_CODE" = "200" ]; then
        echo "OK"
    else
        echo "FAILED (HTTP $HTTP_CODE)"
    fi

    sleep 0.5
done

echo ""
echo "Phase 2: Repeated requests (should hit cache)"
echo "=============================================="
TOTAL_REQUESTS=60
CACHE_HITS=0

for i in $(seq 1 $TOTAL_REQUESTS); do
    # Randomly pick one of the 3 sample requests
    INDEX=$((RANDOM % 3))
    REQUEST="${SAMPLE_REQUESTS[$INDEX]}"

    echo -n "Request $i/${TOTAL_REQUESTS}: "

    RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$API_URL/predict" \
        -H "Content-Type: application/json" \
        -d "$REQUEST")

    HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
    BODY=$(echo "$RESPONSE" | sed '$d')

    if [ "$HTTP_CODE" = "200" ]; then
        # Check latency - cache hits should be very fast (<10ms typically)
        LATENCY=$(echo "$BODY" | grep -o '"latency_ms":[0-9.]*' | cut -d: -f2)

        if [ ! -z "$LATENCY" ]; then
            # If latency < 5ms, likely a cache hit
            IS_FAST=$(echo "$LATENCY < 5" | bc -l 2>/dev/null || echo "0")
            if [ "$IS_FAST" = "1" ]; then
                echo "OK (${LATENCY}ms - likely cache hit)"
                CACHE_HITS=$((CACHE_HITS + 1))
            else
                echo "OK (${LATENCY}ms)"
            fi
        else
            echo "OK"
        fi
    else
        echo "FAILED (HTTP $HTTP_CODE)"
    fi

    # Small delay to avoid overwhelming the API but maintain sustained load
    sleep 0.2
done

echo ""
echo "Phase 3: Burst traffic for P95/P99 metrics"
echo "==========================================="
for i in {1..20}; do
    echo -n "Burst $i/20: "

    # Pick a random sample request
    INDEX=$((RANDOM % 3))
    REQUEST="${SAMPLE_REQUESTS[$INDEX]}"

    curl -s -X POST "$API_URL/predict" \
        -H "Content-Type: application/json" \
        -d "$REQUEST" > /dev/null

    echo "OK"

    # No delay for burst
done

echo ""
echo "================================================================"
echo "Traffic generation complete!"
echo "================================================================"
echo ""
echo "Summary:"
echo "  - Phase 1: 3 initial requests (seeding cache)"
echo "  - Phase 2: $TOTAL_REQUESTS requests (estimated cache hits: ~$CACHE_HITS)"
echo "  - Phase 3: 20 burst requests (for latency percentiles)"
echo "  - Total: $((3 + TOTAL_REQUESTS + 20)) requests"
echo ""
echo "Wait 10-15 seconds for metrics to be scraped by Prometheus, then run:"
echo "  ./scripts/test_prometheus_queries.sh"
echo ""
