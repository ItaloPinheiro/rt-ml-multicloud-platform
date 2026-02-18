# Sample Data Directory Structure

This directory contains sample data for testing, demonstrations, and development of the ML pipeline platform.

## Directory Structure

```
data/sample/
├── demo/                   # Demo-specific data for showcase and testing
│   ├── demo.env           # Demo configuration variables
│   ├── datasets/          # Training and validation datasets
│   ├── requests/          # API request examples
│   └── expected/          # Expected outcomes for validation
├── generated/             # Dynamically generated data
└── production/            # Production-like datasets for realistic testing
    └── datasets/
        └── v1.0/          # Versioned datasets
```

## Directories

### demo/
Contains curated data specifically for running demos and quick tests:
- **datasets/**: Training data for model development
  - `fraud_detection.csv`: Sample fraud detection training data
- **requests/**: API request payloads for testing
  - `baseline_prediction_request.json`: Request for testing initial model
  - `improved_prediction_request.json`: Request for testing improved model
- **expected/**: Expected outcomes for validation
- **demo.env**: Environment configuration for demos

### generated/
Temporary storage for data created by `generate_data.py`:
- `generated/user_features.json`: Raw user profile data
- `generated/transactions.json`: Raw transaction logs
- These files are intermediate artifacts used to create the final CSVs in `demo/datasets`.
- **Do not commit** this folder to git.

### features/
Storage for computed features (e.g., from a Feature Store export):
- Place to store offline feature definitions or point-in-time correct features
- Often used when backfilling feature groups

### predictions/
Target directory for model inference outputs:
- Batch prediction results
- Model evaluation logs
- Should be gitignored (typically validation artifacts, not source code)

### production/
Production-like datasets for more comprehensive testing:
- Organized by version (v1.0, v2.0, etc.)
- Larger, more realistic datasets
- Used for performance testing and validation

## Usage

### In Demo Scripts
```bash
# Source the configuration
source data/sample/demo/demo.env

# Use configured paths
docker exec ml-beam-runner python -m src.models.training.train \
    --data-path /app/${DEMO_DATASET}

# Test API with sample requests
curl -X POST http://localhost:8000/predict \
    -d @${DEMO_REQUEST_V1}
```

### Environment Variables
- `DATA_ROOT`: Root directory for all data (default: `data/sample`)
- `DEMO_ENV`: Environment mode (`local`, `ci`, `staging`)
- `DEMO_MODE`: Enable demo mode (`true`/`false`)

### Data Generation
```bash
# Generate new sample data
python scripts/demo/demo-local/generate_data.py

# Load data into feature store
python scripts/demo/load_sample_data.py
```

## Best Practices

1. **Never modify existing datasets** - Create new versions instead
2. **Use descriptive names** - Files should clearly indicate their purpose
3. **Include metadata** - Document data generation parameters
4. **Separate concerns** - Keep training, testing, and demo data separate
5. **Version control** - Use Git LFS for large files (>1MB)

## Adding New Data

1. Determine the appropriate category (demo, production, generated)
2. Follow the naming conventions:
   - Training data: `{use_case}.csv` or `{use_case}_train.csv`
   - API requests: `{scenario}.json`
   - Responses: `{scenario}_response.json`
3. Update this README with descriptions
4. Add to `.gitignore` if data is generated

## Data Files Description

### Demo Datasets
- **fraud_detection.csv**: 1000 sample transactions with fraud labels
  - Features: transaction amount, merchant category, user history
  - Target: is_fraud (binary)
  - Size: ~40KB

### Demo Requests
- **baseline_prediction_request.json**: Standard prediction request
  - Single transaction features
  - Used for v1 model testing

- **improved_prediction_request.json**: Enhanced prediction request
  - Additional features for v2 model
  - Demonstrates model versioning

## Maintenance

### Cleanup Generated Data
```bash
# Remove all generated data
rm -rf data/sample/generated/*

# Full cleanup (keeps structure)
find data/sample/generated -type f -delete
```

### Verify Data Integrity
```bash
# Check file sizes
du -sh data/sample/*

# Validate JSON files
for f in data/sample/demo/requests/*.json; do
    python -m json.tool "$f" > /dev/null || echo "Invalid: $f"
done
```