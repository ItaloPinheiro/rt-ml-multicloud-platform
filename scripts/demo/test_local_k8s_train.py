#!/usr/bin/env python3
"""
Adapted training script for Local K8s Demo.
"""
import os
import sys

# Set environment to avoid Unicode issues on Windows
os.environ['PYTHONIOENCODING'] = 'utf-8'

import mlflow
import mlflow.sklearn
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import accuracy_score

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
    feature_columns = [col for col in df.columns if col != 'label']
    X = df[feature_columns]
    y = df['label']

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Create Pipeline (Scaler + Model)
    # This ensures the model expects raw feature inputs (with column names) and scales them internally
    print("Training Random Forest Pipeline...")
    pipeline = Pipeline([
        ('scaler', StandardScaler()),
        ('clf', RandomForestClassifier(n_estimators=100, random_state=42))
    ])
    
    # Fit the pipeline
    pipeline.fit(X_train, y_train)

    # Make predictions
    y_pred = pipeline.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    print(f"Accuracy: {accuracy:.3f}")

    # Create or get experiment (Use Default Artifact Root from Server)
    experiment_name = "fraud_detection_local_v3"
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
        mlflow.log_param("n_estimators", 100)
        mlflow.log_metric("accuracy", accuracy)

        # Log model (Pipeline)
        # Infer signature from actual DataFrame inputs to preserve column names
        mlflow.sklearn.log_model(
            pipeline,
            "model",
            signature=mlflow.models.infer_signature(X_test, y_pred),
            registered_model_name="fraud_detector"  # Register immediately
        )

        run_id = run.info.run_id
        print(f"Model logged with run_id: {run_id}")

    # Transition to Production
    print("Transitioning model to Production...")
    client = mlflow.MlflowClient()

    # Get latest version
    versions = client.get_latest_versions("fraud_detector", stages=["None", "Staging", "Production", "Archived"])
    # Sort to ensure we get the absolute latest
    versions.sort(key=lambda x: int(x.version), reverse=True)
    latest_version = versions[0].version if versions else 1

    client.transition_model_version_stage(
        name="fraud_detector",
        version=latest_version,
        stage="Production"
    )
    print(f"Model version {latest_version} transitioned to Production")

if __name__ == "__main__":
    main()
