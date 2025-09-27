# Data Workflow Examples

This document provides concrete examples and sample scripts for working with the `data/` folder structure in various ML pipeline scenarios.

## Example 1: Sample Data Processing Workflow

### Quick Start Script
```bash
#!/bin/bash
# File: scripts/examples/process_sample_data.sh

echo "=== RT ML Platform - Sample Data Processing Example ==="

# Step 1: Prepare data directories
echo "1. Preparing data directories..."
mkdir -p data/raw/sample
mkdir -p data/features/sample
mkdir -p data/predictions/sample

# Step 2: Copy sample data to raw folder for processing
echo "2. Copying sample data to raw folder..."
cp sample_data/small/sample_transactions.json data/raw/sample/
cp sample_data/small/sample_user_features.json data/raw/sample/

echo "   Raw data files:"
ls -la data/raw/sample/

# Step 3: Simulate feature engineering (create processed features)
echo "3. Simulating feature engineering..."
python -c "
import json
import os
from datetime import datetime

# Read raw transaction data
with open('data/raw/sample/sample_transactions.json', 'r') as f:
    transactions = json.load(f)

# Read user features
with open('data/raw/sample/sample_user_features.json', 'r') as f:
    user_features = json.load(f)

# Create engineered features
engineered_features = []
for txn in transactions:
    # Find matching user features
    user_data = next((u for u in user_features if u['user_id'] == txn['user_id']), {})

    # Create feature vector
    feature = {
        'transaction_id': txn['transaction_id'],
        'user_id': txn['user_id'],
        'timestamp': txn['timestamp'],
        'features': {
            'amount': txn['amount'],
            'amount_normalized': txn['amount'] / 1000.0,
            'hour_of_day': int(txn['timestamp'][11:13]),
            'is_weekend': datetime.fromisoformat(txn['timestamp'].replace('Z', '+00:00')).weekday() >= 5,
            'merchant_category_encoded': hash(txn['merchant_category']) % 100,
            'payment_method_encoded': {'credit': 1, 'debit': 2, 'cash': 3}.get(txn['payment_method'], 0),
            'user_age': user_data.get('age', 0),
            'user_income_bracket': user_data.get('income_bracket', 0),
            'user_transaction_count': user_data.get('transaction_count', 0),
            'location_risk_score': user_data.get('location_risk_score', 0.5)
        }
    }
    engineered_features.append(feature)

# Save engineered features
with open('data/features/sample/transaction_features.json', 'w') as f:
    json.dump(engineered_features, f, indent=2)

print(f'Generated {len(engineered_features)} feature vectors')
"

echo "   Feature files:"
ls -la data/features/sample/

# Step 4: Simulate model predictions
echo "4. Simulating model predictions..."
python -c "
import json
import random
from datetime import datetime

# Read engineered features
with open('data/features/sample/transaction_features.json', 'r') as f:
    features = json.load(f)

# Generate predictions
predictions = []
for feature in features:
    # Simulate fraud detection model
    amount = feature['features']['amount']
    hour = feature['features']['hour_of_day']
    risk_score = feature['features']['location_risk_score']

    # Simple heuristic for demo
    fraud_probability = (
        0.1 * (amount > 500) +  # Large amounts slightly more risky
        0.2 * (hour < 6 or hour > 22) +  # Unusual hours
        0.3 * risk_score +  # Location risk
        random.uniform(0, 0.4)  # Random component
    )
    fraud_probability = min(fraud_probability, 1.0)

    prediction = {
        'transaction_id': feature['transaction_id'],
        'user_id': feature['user_id'],
        'timestamp': datetime.now().isoformat(),
        'prediction': {
            'fraud_probability': round(fraud_probability, 3),
            'is_fraud': fraud_probability > 0.5,
            'confidence': round(random.uniform(0.7, 0.95), 3),
            'model_version': 'demo_v1.0',
            'features_used': list(feature['features'].keys())
        }
    }
    predictions.append(prediction)

# Save predictions
with open('data/predictions/sample/fraud_predictions.json', 'w') as f:
    json.dump(predictions, f, indent=2)

print(f'Generated {len(predictions)} predictions')
high_risk = sum(1 for p in predictions if p['prediction']['is_fraud'])
print(f'High risk transactions: {high_risk}/{len(predictions)}')
"

echo "   Prediction files:"
ls -la data/predictions/sample/

# Step 5: Generate summary report
echo "5. Generating summary report..."
python -c "
import json
import os
from datetime import datetime

# Collect statistics
stats = {
    'pipeline_run': {
        'timestamp': datetime.now().isoformat(),
        'status': 'completed'
    },
    'data_processed': {
        'raw_files': len(os.listdir('data/raw/sample/')),
        'feature_files': len(os.listdir('data/features/sample/')),
        'prediction_files': len(os.listdir('data/predictions/sample/'))
    }
}

# Read predictions for analysis
with open('data/predictions/sample/fraud_predictions.json', 'r') as f:
    predictions = json.load(f)

stats['predictions'] = {
    'total_transactions': len(predictions),
    'high_risk_count': sum(1 for p in predictions if p['prediction']['is_fraud']),
    'average_fraud_probability': round(sum(p['prediction']['fraud_probability'] for p in predictions) / len(predictions), 3),
    'high_risk_percentage': round(100 * sum(1 for p in predictions if p['prediction']['is_fraud']) / len(predictions), 1)
}

# Save summary
with open('data/pipeline_summary.json', 'w') as f:
    json.dump(stats, f, indent=2)

print('\\n=== Pipeline Summary ===')
print(f'Total transactions processed: {stats[\"predictions\"][\"total_transactions\"]}')
print(f'High risk transactions: {stats[\"predictions\"][\"high_risk_count\"]} ({stats[\"predictions\"][\"high_risk_percentage\"]}%)')
print(f'Average fraud probability: {stats[\"predictions\"][\"average_fraud_probability\"]}')
print(f'\\nSummary saved to: data/pipeline_summary.json')
"

echo ""
echo "=== Data Processing Complete ==="
echo "Check the following directories:"
echo "  - data/raw/sample/ (raw input data)"
echo "  - data/features/sample/ (engineered features)"
echo "  - data/predictions/sample/ (model predictions)"
echo "  - data/pipeline_summary.json (summary report)"
```

## Example 2: Continuous Data Processing Simulation

### Streaming Data Simulation Script
```python
#!/usr/bin/env python3
# File: scripts/examples/simulate_streaming_data.py

import json
import time
import random
import os
from datetime import datetime, timedelta
from typing import List, Dict

def generate_streaming_transaction() -> Dict:
    """Generate a realistic streaming transaction."""
    user_ids = [f"user_{i:03d}" for i in range(1, 51)]
    merchants = ["amazon", "walmart", "starbucks", "shell", "target", "uber", "netflix"]
    categories = ["retail", "grocery", "coffee", "gas", "retail", "transport", "entertainment"]
    payment_methods = ["credit", "debit", "digital_wallet"]

    return {
        "transaction_id": f"txn_{random.randint(100000, 999999)}",
        "user_id": random.choice(user_ids),
        "timestamp": datetime.now().isoformat() + "Z",
        "amount": round(random.uniform(5.0, 1000.0), 2),
        "merchant_id": f"merchant_{random.choice(merchants)}",
        "merchant_category": random.choice(categories),
        "payment_method": random.choice(payment_methods),
        "location": {
            "city": random.choice(["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"]),
            "state": random.choice(["NY", "CA", "IL", "TX", "AZ"]),
            "country": "US"
        }
    }

def simulate_streaming_ingestion(duration_minutes: int = 5):
    """Simulate streaming data ingestion for specified duration."""
    print(f"Starting streaming simulation for {duration_minutes} minutes...")

    # Create timestamped directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_dir = f"data/raw/streaming_{timestamp}"
    os.makedirs(raw_dir, exist_ok=True)

    end_time = datetime.now() + timedelta(minutes=duration_minutes)
    batch_count = 0

    while datetime.now() < end_time:
        # Generate batch of transactions
        batch_size = random.randint(5, 15)
        transactions = [generate_streaming_transaction() for _ in range(batch_size)]

        # Save batch
        batch_file = f"{raw_dir}/batch_{batch_count:04d}.json"
        with open(batch_file, 'w') as f:
            json.dump(transactions, f, indent=2)

        print(f"Generated batch {batch_count} with {batch_size} transactions -> {batch_file}")
        batch_count += 1

        # Wait before next batch (simulate real streaming interval)
        time.sleep(random.uniform(10, 30))  # 10-30 seconds between batches

    print(f"Streaming simulation complete. Generated {batch_count} batches in {raw_dir}")
    return raw_dir

def process_streaming_batches(raw_dir: str):
    """Process streaming batches into features."""
    print(f"Processing batches from {raw_dir}...")

    # Create features directory
    features_dir = raw_dir.replace("/raw/", "/features/")
    os.makedirs(features_dir, exist_ok=True)

    # Process each batch
    batch_files = [f for f in os.listdir(raw_dir) if f.endswith('.json')]

    for batch_file in sorted(batch_files):
        print(f"Processing {batch_file}...")

        # Read batch
        with open(f"{raw_dir}/{batch_file}", 'r') as f:
            transactions = json.load(f)

        # Engineer features for each transaction
        features = []
        for txn in transactions:
            feature = {
                "transaction_id": txn["transaction_id"],
                "user_id": txn["user_id"],
                "timestamp": txn["timestamp"],
                "features": {
                    "amount": txn["amount"],
                    "amount_log": round(math.log(txn["amount"] + 1), 3),
                    "hour_of_day": int(txn["timestamp"][11:13]),
                    "day_of_week": datetime.fromisoformat(txn["timestamp"].replace('Z', '+00:00')).weekday(),
                    "is_weekend": datetime.fromisoformat(txn["timestamp"].replace('Z', '+00:00')).weekday() >= 5,
                    "merchant_category_hash": hash(txn["merchant_category"]) % 100,
                    "payment_method_encoded": {"credit": 1, "debit": 2, "digital_wallet": 3}.get(txn["payment_method"], 0),
                    "location_hash": hash(f"{txn['location']['city']}_{txn['location']['state']}") % 1000
                }
            }
            features.append(feature)

        # Save processed features
        feature_file = f"{features_dir}/{batch_file}"
        with open(feature_file, 'w') as f:
            json.dump(features, f, indent=2)

    print(f"Feature processing complete. Results in {features_dir}")
    return features_dir

if __name__ == "__main__":
    import math
    import argparse

    parser = argparse.ArgumentParser(description="Simulate streaming data processing")
    parser.add_argument("--duration", type=int, default=2, help="Simulation duration in minutes")
    parser.add_argument("--process-only", type=str, help="Process existing raw data directory")

    args = parser.parse_args()

    if args.process_only:
        process_streaming_batches(args.process_only)
    else:
        raw_dir = simulate_streaming_ingestion(args.duration)
        process_streaming_batches(raw_dir)
```

## Example 3: Data Quality Validation

### Data Validation Script
```python
#!/usr/bin/env python3
# File: scripts/examples/validate_data_quality.py

import json
import os
from datetime import datetime
from typing import Dict, List, Any

def validate_raw_data(file_path: str) -> Dict[str, Any]:
    """Validate raw transaction data quality."""
    with open(file_path, 'r') as f:
        data = json.load(f)

    validation_results = {
        "file": file_path,
        "timestamp": datetime.now().isoformat(),
        "total_records": len(data),
        "validation_passed": True,
        "issues": []
    }

    for i, record in enumerate(data):
        # Check required fields
        required_fields = ["transaction_id", "user_id", "timestamp", "amount"]
        for field in required_fields:
            if field not in record:
                validation_results["issues"].append({
                    "record_index": i,
                    "issue": f"Missing required field: {field}"
                })
                validation_results["validation_passed"] = False

        # Check data types and ranges
        if "amount" in record:
            try:
                amount = float(record["amount"])
                if amount <= 0 or amount > 100000:
                    validation_results["issues"].append({
                        "record_index": i,
                        "issue": f"Amount out of valid range: {amount}"
                    })
                    validation_results["validation_passed"] = False
            except (ValueError, TypeError):
                validation_results["issues"].append({
                    "record_index": i,
                    "issue": f"Invalid amount format: {record.get('amount')}"
                })
                validation_results["validation_passed"] = False

    return validation_results

def validate_feature_data(file_path: str) -> Dict[str, Any]:
    """Validate engineered feature data quality."""
    with open(file_path, 'r') as f:
        data = json.load(f)

    validation_results = {
        "file": file_path,
        "timestamp": datetime.now().isoformat(),
        "total_records": len(data),
        "validation_passed": True,
        "issues": []
    }

    for i, record in enumerate(data):
        # Check feature structure
        if "features" not in record:
            validation_results["issues"].append({
                "record_index": i,
                "issue": "Missing features object"
            })
            validation_results["validation_passed"] = False
            continue

        features = record["features"]

        # Check for null/NaN values
        for feature_name, feature_value in features.items():
            if feature_value is None or (isinstance(feature_value, float) and str(feature_value).lower() == 'nan'):
                validation_results["issues"].append({
                    "record_index": i,
                    "issue": f"Null/NaN value in feature: {feature_name}"
                })
                validation_results["validation_passed"] = False

    return validation_results

def run_data_quality_checks():
    """Run comprehensive data quality checks across all data folders."""
    print("=== Data Quality Validation ===")

    validation_report = {
        "timestamp": datetime.now().isoformat(),
        "overall_status": "PASSED",
        "validations": {
            "raw_data": [],
            "feature_data": [],
            "prediction_data": []
        }
    }

    # Validate raw data
    raw_data_path = "data/raw"
    if os.path.exists(raw_data_path):
        for root, dirs, files in os.walk(raw_data_path):
            for file in files:
                if file.endswith('.json'):
                    file_path = os.path.join(root, file)
                    result = validate_raw_data(file_path)
                    validation_report["validations"]["raw_data"].append(result)
                    if not result["validation_passed"]:
                        validation_report["overall_status"] = "FAILED"

    # Validate feature data
    features_path = "data/features"
    if os.path.exists(features_path):
        for root, dirs, files in os.walk(features_path):
            for file in files:
                if file.endswith('.json'):
                    file_path = os.path.join(root, file)
                    result = validate_feature_data(file_path)
                    validation_report["validations"]["feature_data"].append(result)
                    if not result["validation_passed"]:
                        validation_report["overall_status"] = "FAILED"

    # Save validation report
    report_file = "data/data_quality_report.json"
    with open(report_file, 'w') as f:
        json.dump(validation_report, f, indent=2)

    # Print summary
    print(f"Data quality validation complete: {validation_report['overall_status']}")
    print(f"Raw data files validated: {len(validation_report['validations']['raw_data'])}")
    print(f"Feature data files validated: {len(validation_report['validations']['feature_data'])}")
    print(f"Detailed report saved to: {report_file}")

    return validation_report

if __name__ == "__main__":
    run_data_quality_checks()
```

## Example 4: Data Cleanup and Maintenance

### Cleanup Script
```bash
#!/bin/bash
# File: scripts/examples/data_maintenance.sh

echo "=== Data Maintenance and Cleanup ==="

# Configuration
RETENTION_DAYS=${DATA_RETENTION_DAYS:-7}
DRY_RUN=${DRY_RUN:-false}

echo "Retention policy: ${RETENTION_DAYS} days"
echo "Dry run mode: ${DRY_RUN}"

# Function to safely remove old files
cleanup_old_files() {
    local directory=$1
    local retention_days=$2
    local description=$3

    if [ ! -d "$directory" ]; then
        echo "Directory $directory does not exist, skipping..."
        return
    fi

    echo ""
    echo "Cleaning up $description in $directory (older than $retention_days days)..."

    if [ "$DRY_RUN" = "true" ]; then
        find "$directory" -type f -mtime +$retention_days -ls
    else
        local count=$(find "$directory" -type f -mtime +$retention_days | wc -l)
        find "$directory" -type f -mtime +$retention_days -delete
        echo "Removed $count old files"
    fi
}

# Cleanup old raw data
cleanup_old_files "data/raw" $RETENTION_DAYS "raw data files"

# Cleanup old feature data
cleanup_old_files "data/features" $RETENTION_DAYS "feature data files"

# Cleanup old predictions (keep longer - 30 days)
cleanup_old_files "data/predictions" 30 "prediction files"

# Archive important data before cleanup
echo ""
echo "Archiving recent important data..."
ARCHIVE_DATE=$(date +%Y%m%d)
ARCHIVE_DIR="data/archives/$ARCHIVE_DATE"

if [ "$DRY_RUN" = "false" ]; then
    mkdir -p "$ARCHIVE_DIR"

    # Archive last 24 hours of data
    find data/raw -name "*.json" -mtime -1 -exec cp {} "$ARCHIVE_DIR/" \; 2>/dev/null || true
    find data/features -name "*.json" -mtime -1 -exec cp {} "$ARCHIVE_DIR/" \; 2>/dev/null || true

    ARCHIVED_COUNT=$(ls "$ARCHIVE_DIR" 2>/dev/null | wc -l)
    echo "Archived $ARCHIVED_COUNT recent files to $ARCHIVE_DIR"
fi

# Generate storage usage report
echo ""
echo "=== Storage Usage Report ==="
du -sh data/raw 2>/dev/null || echo "data/raw: 0B"
du -sh data/features 2>/dev/null || echo "data/features: 0B"
du -sh data/predictions 2>/dev/null || echo "data/predictions: 0B"
du -sh data/archives 2>/dev/null || echo "data/archives: 0B"
echo "Total data directory size: $(du -sh data 2>/dev/null | cut -f1)"

echo ""
echo "Data maintenance complete!"
```

## Integration with Docker Compose

Add to your `docker-compose.yml` for automated data processing:

```yaml
  # Data Processing Service
  data-processor:
    build:
      context: .
      dockerfile: docker/Dockerfile
    container_name: ml-data-processor
    volumes:
      - ./data:/app/data
      - ./sample_data:/app/sample_data
      - ./scripts:/app/scripts
    environment:
      - PYTHONPATH=/app
      - DATA_RETENTION_DAYS=7
    command: ["python", "scripts/examples/process_sample_data.py"]
    depends_on:
      redis:
        condition: service_healthy
    profiles:
      - data-processing
```

## Usage Instructions

1. **Make scripts executable:**
   ```bash
   chmod +x scripts/examples/*.sh
   chmod +x scripts/examples/*.py
   ```

2. **Run sample data processing:**
   ```bash
   ./scripts/examples/process_sample_data.sh
   ```

3. **Run streaming simulation:**
   ```bash
   python scripts/examples/simulate_streaming_data.py --duration 5
   ```

4. **Run data quality validation:**
   ```bash
   python scripts/examples/validate_data_quality.py
   ```

5. **Run data maintenance:**
   ```bash
   ./scripts/examples/data_maintenance.sh
   ```

These examples demonstrate practical usage of the `data/` folder structure and provide a foundation for real ML pipeline operations.