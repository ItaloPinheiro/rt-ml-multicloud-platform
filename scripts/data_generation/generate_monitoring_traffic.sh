#!/bin/bash
# Generate diverse prediction traffic for Prometheus monitoring

echo "Generating 20 diverse predictions..."

for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  AMOUNT=$((100 + i * 50))
  RISK=$((i * 5))
  HOUR=$((i % 24))
  DOW=$((i % 7))
  MERCHANT=$((i * 7 % 100))
  PAYMENT=$((i % 5))

  curl -s -X POST http://localhost:8000/predict \
    -H "Content-Type: application/json" \
    -d "{
      \"features\": {
        \"amount\": ${AMOUNT}.0,
        \"merchant_category_encoded\": ${MERCHANT},
        \"payment_method_encoded\": ${PAYMENT},
        \"hour_of_day\": ${HOUR},
        \"day_of_week\": ${DOW},
        \"is_weekend\": $((DOW >= 5 ? 1 : 0)),
        \"transaction_count_24h\": ${i},
        \"avg_amount_30d\": 231.04,
        \"risk_score\": 0.${RISK}
      },
      \"model_name\": \"fraud_detector\",
      \"return_probabilities\": true
    }" > /dev/null 2>&1

  if [ $? -eq 0 ]; then
    echo "Request $i/20 - Amount: $AMOUNT, Risk: 0.$RISK - OK"
  else
    echo "Request $i/20 - FAILED"
  fi

  sleep 0.3
done

echo ""
echo "Traffic generation complete!"
echo ""