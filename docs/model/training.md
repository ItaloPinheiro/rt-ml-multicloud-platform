# Model Training Documentation

## Overview
This document describes the training process for the **Fraud Detection Model** used in the RT ML Platform demo. The model is a **Random Forest Classifier** trained on synthetic transaction data to identify potentially fraudulent transactions.

## 1. Dataset

*   **Source:** `data/sample/demo/datasets/fraud_detection.csv`
*   **Description:** Synthetic dataset representing credit card transactions.
*   **Size:** ~1000 records (Demo scale)
*   **Target Variable:** `label` (0 = Legitimate, 1 = Fraud)

### Feature Schema

| Feature Name | Type | Description |
| :--- | :--- | :--- |
| `hour_of_day` | Float | Hour transaction occurred (0-23) |
| `day_of_week` | Float | Day of week (0-6) |
| `is_weekend` | Boolean | True if Saturday/Sunday |
| `transaction_count_24h` | Float | Count of user transactions in last 24h (Velocity) |
| `avg_amount_30d` | Float | Average transaction amount in last 30 days |
| `risk_score` | Float | External risk score (0-1) |
| `amount` | Float | Transaction amount |
| `merchant_category_encoded` | Float | Encoded category ID of merchant |
| `payment_method_encoded` | Float | Encoded ID of payment method |

## 2. Training Pipeline

The training script (`scripts/demo/demo-aws/train.py`) implements a Scikit-Learn Pipeline with the following stages:

1.  **Data Loading & Cleaning**:
    *   Loads CSV data.
    *   Casts integer columns to `float64` to prevent MLflow warnings about missing value handling.
    *   Splits data into **80% Training** and **20% Testing** sets.

2.  **Preprocessing**:
    *   **StandardScaler**: Standardizes features by removing the mean and scaling to unit variance. This ensures all features contribute equally to the distance metrics (critical for stable convergence, though Random Forest is robust to scaling).

3.  **Model Architecture**:
    *   **Algorithm**: Random Forest Classifier (`sklearn.ensemble.RandomForestClassifier`)
    *   **Hyperparameters**:
        *   `n_estimators`: Number of trees (default: 100, can be overridden via CLI).
        *   `random_state`: Fixed at 42 for reproducibility.

## 3. MLflow Integration

The training process is fully tracked by MLflow:

### Tracking
*   **Experiment Name**: `fraud_detection_local`
*   **Parameters Logged**:
    *   `model_type`: "random_forest_pipeline"
    *   `n_estimators`: (e.g., 100 or 200)
*   **Metrics Logged**:
    *   `accuracy`: Test set accuracy score.
*   **Artifacts Logged**:
    *   The entire Scikit-Learn Pipeline object (including scaler and model) is pickled and saved.
    *   **Input Signature**: Inferred from the test dataset to enforce schema validation during serving.

### Model Registry & Promotion
1.  **Registration**: The model is properly registered in the MLflow Model Registry under the name **`fraud_detector`**.
2.  **Versioning**: Each run creates a new incrementing version (e.g., v1, v2).
3.  **Auto-Promotion**:
    *   The script automatically promotes the newly trained model to **Production**.
    *   It assigns the **`production`** alias to the new version.
    *   It also sets a custom tag `deployment_status="production"`.

## 4. Execution

To train the model (assuming you are in the project root):

### Default Training (Baseline)
```bash
python scripts/demo/demo-aws/train.py
```

### Hyperparameter Tuning (Improved Model)
To simulate a model upgrade, increase the number of estimators:
```bash
python scripts/demo/demo-aws/train.py --n-estimators 200
```

## 5. Verification

After training, the script automatically verifies the deployment:
1.  It waits for the API to update its served version (polling every 10s).
2.  It sends a test prediction to the API endpoint (`$API_URL/predict`).
3.  It confirms the API returns the **new model version** and checks latency.
