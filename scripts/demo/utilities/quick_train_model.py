#!/usr/bin/env python3
"""
Quick model training script for demo purposes.
"""
import os
import sys

# Set environment to avoid Unicode issues on Windows
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['MLFLOW_DISABLE_ENV_MANAGER_CONDA_WARNING'] = 'TRUE'

import mlflow
import mlflow.sklearn
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import accuracy_score, precision_score, recall_score

# Set MLflow tracking URI and S3 configuration
mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"))

# Configure S3 for artifact storage
os.environ["AWS_ACCESS_KEY_ID"] = "minioadmin"
os.environ["AWS_SECRET_ACCESS_KEY"] = "minioadmin123"
os.environ["MLFLOW_S3_ENDPOINT_URL"] = "http://localhost:9000"

# Configuration
DATA_ROOT = os.getenv("DATA_ROOT", "sample_data")
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

    # Create Pipeline
    # This ensures the model expects raw feature inputs (with column names) and scales them internally
    print("Training Random Forest Pipeline...")
    pipeline = Pipeline([
        ('scaler', StandardScaler()),
        ('clf', RandomForestClassifier(n_estimators=100, random_state=42))
    ])
    
    pipeline.fit(X_train, y_train)

    # Make predictions
    y_pred = pipeline.predict(X_test)

    # Calculate metrics
    accuracy = accuracy_score(y_test, y_pred)
    precision = precision_score(y_test, y_pred, zero_division=0)
    recall = recall_score(y_test, y_pred, zero_division=0)

    print(f"Accuracy: {accuracy:.3f}")
    print(f"Precision: {precision:.3f}")
    print(f"Recall: {recall:.3f}")

    # Create or get experiment with S3 artifact location
    experiment_name = "fraud_detection_demo"
    try:
        experiment = mlflow.get_experiment_by_name(experiment_name)
        if experiment is None:
            # Create experiment with S3 artifact location
            artifact_location = "s3://mlflow/fraud_detection_demo"
            experiment_id = mlflow.create_experiment(
                experiment_name,
                artifact_location=artifact_location
            )
            print(f"Created experiment with S3 storage: {artifact_location}")
        else:
            experiment_id = experiment.experiment_id
            print(f"Using existing experiment, artifact location: {experiment.artifact_location}")
    except Exception as e:
        print(f"Using default experiment: {e}")
        experiment_id = "0"

    # Log to MLflow
    print("Logging model to MLflow...")
    try:
        with mlflow.start_run(experiment_id=experiment_id) as run:
            # Log parameters
            mlflow.log_param("model_type", "random_forest_pipeline")
            mlflow.log_param("n_estimators", 100)
            mlflow.log_param("test_size", 0.2)

            # Log metrics
            mlflow.log_metric("accuracy", accuracy)
            mlflow.log_metric("precision", precision)
            mlflow.log_metric("recall", recall)

            # Log model (Pipeline)
            # Infer signature from actual DataFrame inputs to preserve column names
            mlflow.sklearn.log_model(
                pipeline,
                "model",
                signature=mlflow.models.infer_signature(X_test, y_pred)
            )

            # Save run ID for registration
            run_id = run.info.run_id
            print(f"Model logged with run_id: {run_id}")

    except Exception as e:
        print(f"Error during MLflow logging: {e}")
        sys.exit(1)

    # Register model separately
    try:
        print("Registering model...")
        client = mlflow.MlflowClient()

        # Create registered model
        try:
            client.create_registered_model("fraud_detector")
            print("Created new registered model: fraud_detector")
        except Exception:
            print("Registered model already exists")

        # Create model version
        model_version = client.create_model_version(
            name="fraud_detector",
            source=f"runs:/{run_id}/model",
            run_id=run_id
        )

        print(f"Registered model version: {model_version.version}")

        # Transition to production
        client.transition_model_version_stage(
            name="fraud_detector",
            version=model_version.version,
            stage="Production"
        )
        print("Model transitioned to Production stage")

    except Exception as e:
        print(f"Model registration failed (this is okay for demo): {e}")

    print("\nModel training complete!")
    print(f"MLflow UI: http://localhost:5000")
    if run_id:
        print(f"Run ID: {run_id}")
        print(f"View run: http://localhost:5000/#/experiments/{experiment_id}/runs/{run_id}")

if __name__ == "__main__":
    main()