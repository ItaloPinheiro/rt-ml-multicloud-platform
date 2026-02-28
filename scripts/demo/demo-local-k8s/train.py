#!/usr/bin/env python3
"""
Adapted training script for Local K8s Demo.
"""
import argparse
import os
import sys

# Reconfigure stdout/stderr to UTF-8 before any imports that may print emoji
# (MLflow 3.x prints a runner emoji in end_run(); cp1252 on Windows cannot encode it)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import mlflow
import mlflow.sklearn
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

# Set MLflow tracking URI for Local K8s (NodePort 30000)
mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:30000"))

# Configuration
DATA_ROOT = os.getenv("DATA_ROOT", "data/sample")
DEMO_DATASET = os.path.join(DATA_ROOT, "demo", "datasets", "fraud_detection.csv")


def main():
    # Load data
    print(f"Loading training data from {DEMO_DATASET}...")
    if not os.path.exists(DEMO_DATASET):
        print(f"Error: Dataset not found at {DEMO_DATASET}")
        sys.exit(1)

    df = pd.read_csv(DEMO_DATASET)

    # Prepare features and target
    feature_columns = [col for col in df.columns if col != "label"]
    X = df[feature_columns]
    y = df["label"]

    # Cast integer columns to float64 for nullable-safe schema inference
    # This prevents MLflow UserWarning about integer columns not handling missing values
    int_columns = X.select_dtypes(include=["int64", "int32"]).columns
    X = X.copy()  # Avoid SettingWithCopyWarning
    X[int_columns] = X[int_columns].astype("float64")

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    parser = argparse.ArgumentParser(description="Train fraud detection model")
    parser.add_argument(
        "--n-estimators", type=int, default=100, help="Number of trees in Random Forest"
    )
    args = parser.parse_args()

    # Create Pipeline (Scaler + Model)
    # This ensures the model expects raw feature inputs (with column names) and scales them internally
    print(f"Training Random Forest Pipeline with n_estimators={args.n_estimators}...")
    pipeline = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "clf",
                RandomForestClassifier(n_estimators=args.n_estimators, random_state=42),
            ),
        ]
    )

    # Fit the pipeline
    pipeline.fit(X_train, y_train)

    # Make predictions
    y_pred = pipeline.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    print(f"Accuracy: {accuracy:.3f}")

    # Create or get experiment (Use Default Artifact Root from Server)
    experiment_name = "fraud_detection_local_k8s"
    try:
        experiment = mlflow.get_experiment_by_name(experiment_name)
        if experiment is None:
            print(f"Creating new experiment: {experiment_name}")
            experiment_id = mlflow.create_experiment(experiment_name)
        else:
            experiment_id = experiment.experiment_id
            print(f"Using existing experiment: {experiment_name} (ID: {experiment_id})")
    except Exception as e:
        print(f"Error getting experiment: {e}")
        experiment_id = "0"

    # Log to MLflow
    print("Logging model to MLflow...")
    with mlflow.start_run(experiment_id=experiment_id) as run:
        mlflow.log_param("model_type", "random_forest_pipeline")
        mlflow.log_param("n_estimators", args.n_estimators)
        mlflow.log_metric("accuracy", accuracy)

        # Log model (Pipeline)
        # Infer signature from actual DataFrame inputs to preserve column names
        mlflow.sklearn.log_model(
            sk_model=pipeline,
            name="model",  # MLflow 2.9+ uses 'name' instead of 'artifact_path'
            signature=mlflow.models.infer_signature(X_test, y_pred),
            registered_model_name="fraud_detector",  # Register immediately
        )

        run_id = run.info.run_id
        print(f"Model logged with run_id: {run_id}")

    # Transition to Production (Method 1: Tags/Aliases for Modern MLflow)
    print("Promoting model to Production...")
    client = mlflow.MlflowClient()

    # Get latest version
    versions = client.search_model_versions("name='fraud_detector'")
    versions.sort(key=lambda x: int(x.version), reverse=True)
    latest_version = versions[0].version if versions else "1"

    print(f"Latest version found: {latest_version}")

    # 1. Set 'production' alias (Recommended for MLflow 2.9+)
    try:
        client.set_registered_model_alias(
            "fraud_detector", "production", latest_version
        )
        print(f"assigned alias 'production' to version {latest_version}")
    except Exception as e:
        print(f"Warning: Could not set alias: {e}")

    # 2. Set 'deployment_status' tag (Custom convention)
    try:
        client.set_model_version_tag(
            "fraud_detector", latest_version, "deployment_status", "production"
        )
        print(
            f"Set 'deployment_status' tag to 'production' for version {latest_version}"
        )
    except Exception as e:
        print(f"Warning: Could not set tag: {e}")

    # --- Verification Step ---
    print("\n--- Verifying Model Serving ---")
    import time

    import requests

    API_URL = os.getenv("API_URL", "http://localhost:30001")
    PREDICT_URL = f"{API_URL}/predict"

    # Payload matching the schema used in training
    test_payload = {
        "features": {
            "hour_of_day": 21.0,
            "day_of_week": 0.0,
            "is_weekend": False,
            "transaction_count_24h": 4.0,
            "avg_amount_30d": 170.75,
            "risk_score": 0.283,
            "amount": 395.67,
            "merchant_category_encoded": 0.0,
            "payment_method_encoded": 1.0,
        },
        "model_name": "fraud_detector",
        "return_probabilities": True,
    }

    print(f"Waiting for API to pick up model version {latest_version}...")

    max_retries = 10
    retry_delay = 10  # API updates every 60s by default, so we might wait up to 60s

    for i in range(max_retries):
        try:
            # Send prediction request
            start_time = time.time()
            response = requests.post(PREDICT_URL, json=test_payload)
            latency = (time.time() - start_time) * 1000

            if response.status_code == 200:
                result = response.json()
                served_version = result.get("model_version")

                print(
                    f"Attempt {i+1}: API served version {served_version} in {latency:.2f}ms"
                )

                if str(served_version) == str(latest_version):
                    print(
                        f"OK: API is serving the expected version {latest_version}"
                    )

                    # Verify Latency SLA (e.g., < 200ms) - Note: First hit might be slower due to loading
                    if i > 0 and latency < 200:
                        print("OK: Latency within acceptable limits (<200ms)")
                    elif i == 0:
                        print(f"INFO: First hit latency: {latency:.2f}ms (Cold start)")
                    else:
                        print(f"WARN: High latency detected: {latency:.2f}ms")

                    break
                else:
                    print(
                        f"WAIT: Waiting for version update (Current: {served_version}, Expected: {latest_version})..."
                    )
            else:
                print(f"ERROR: API Error {response.status_code}: {response.text}")

        except Exception as e:
            print(f"ERROR: Connection Error: {e}")

        time.sleep(retry_delay)
    else:
        print(
            f"TIMEOUT: API did not update to version {latest_version} within {max_retries * retry_delay} seconds."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
