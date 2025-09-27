#!/usr/bin/env python3
"""
Train a fraud detection model for the ML pipeline demo.
This script trains a model using the generated sample data.
"""

import os
import sys
import json
import pandas as pd
import numpy as np
import mlflow
import mlflow.sklearn
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score
from sklearn.preprocessing import StandardScaler
import argparse
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def setup_mlflow():
    """Setup MLflow tracking."""
    # Set MLflow tracking URI
    mlflow_uri = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
    mlflow.set_tracking_uri(mlflow_uri)

    # Set experiment
    experiment_name = "fraud_detection_demo"
    try:
        experiment = mlflow.get_experiment_by_name(experiment_name)
        if experiment is None:
            mlflow.create_experiment(experiment_name)
        mlflow.set_experiment(experiment_name)
    except Exception as e:
        logger.warning(f"Could not set MLflow experiment: {e}")

def load_training_data(data_path: str = "sample_data/small/training_data.csv") -> tuple:
    """Load and prepare training data."""
    if not os.path.exists(data_path):
        logger.error(f"Training data not found at {data_path}")
        logger.info("Please run 'python scripts/demo/generate_data.py' first to generate sample data")
        sys.exit(1)

    logger.info(f"Loading training data from {data_path}")
    df = pd.read_csv(data_path)

    # Prepare features and target
    feature_columns = [col for col in df.columns if col != 'label']
    X = df[feature_columns]
    y = df['label']

    logger.info(f"Dataset shape: {X.shape}")
    logger.info(f"Features: {list(X.columns)}")
    logger.info(f"Fraud rate: {y.mean():.3f}")

    return X, y, feature_columns

def train_model(X_train, X_test, y_train, y_test, model_type: str = "random_forest") -> tuple:
    """Train and evaluate a fraud detection model."""

    # Scale features
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # Initialize model based on type
    if model_type == "logistic":
        model = LogisticRegression(random_state=42, max_iter=1000)
    elif model_type == "random_forest":
        model = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            random_state=42,
            class_weight='balanced'
        )
    else:
        raise ValueError(f"Unknown model type: {model_type}")

    logger.info(f"Training {model_type} model...")

    # Start MLflow run
    with mlflow.start_run(run_name=f"fraud_detector_{model_type}"):
        # Log parameters
        if hasattr(model, 'get_params'):
            for param, value in model.get_params().items():
                mlflow.log_param(param, value)

        # Train model
        model.fit(X_train_scaled, y_train)

        # Make predictions
        y_pred = model.predict(X_test_scaled)
        y_pred_proba = model.predict_proba(X_test_scaled)[:, 1]

        # Calculate metrics
        metrics = {
            'accuracy': accuracy_score(y_test, y_pred),
            'precision': precision_score(y_test, y_pred),
            'recall': recall_score(y_test, y_pred),
            'f1_score': f1_score(y_test, y_pred),
            'roc_auc': roc_auc_score(y_test, y_pred_proba)
        }

        # Log metrics
        for metric_name, metric_value in metrics.items():
            mlflow.log_metric(metric_name, metric_value)

        # Log model
        mlflow.sklearn.log_model(
            model,
            "model",
            registered_model_name="fraud_detector"
        )

        # Log scaler as artifact
        import joblib
        scaler_path = "scaler.pkl"
        joblib.dump(scaler, scaler_path)
        mlflow.log_artifact(scaler_path)
        os.remove(scaler_path)

        # Log feature importance if available
        if hasattr(model, 'feature_importances_'):
            feature_importance = dict(zip(X_train.columns, model.feature_importances_))
            # Log top 10 most important features
            sorted_features = sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)
            for i, (feature, importance) in enumerate(sorted_features[:10]):
                mlflow.log_metric(f"feature_importance_{feature}", importance)

        # Print results
        logger.info("Model training completed!")
        logger.info("Metrics:")
        for metric_name, metric_value in metrics.items():
            logger.info(f"  {metric_name}: {metric_value:.4f}")

        # Get run info
        run = mlflow.active_run()
        logger.info(f"MLflow run ID: {run.info.run_id}")

        return model, scaler, metrics

def create_model_metadata():
    """Create model metadata for the API."""
    metadata = {
        "model_name": "fraud_detector",
        "model_type": "fraud_detection",
        "version": "1.0.0",
        "description": "Demo fraud detection model for credit card transactions",
        "features": [
            "amount",
            "hour_of_day",
            "day_of_week",
            "is_weekend",
            "transaction_count_24h",
            "avg_amount_30d",
            "risk_score",
            "merchant_category_encoded",
            "payment_method_encoded"
        ],
        "target": "fraud_probability",
        "threshold": 0.5,
        "created_at": pd.Timestamp.now().isoformat()
    }

    # Save metadata
    os.makedirs("models/metadata", exist_ok=True)
    with open("models/metadata/fraud_detector.json", "w") as f:
        json.dump(metadata, f, indent=2)

    logger.info("Model metadata saved to models/metadata/fraud_detector.json")

def main():
    """Main training function."""
    parser = argparse.ArgumentParser(description="Train fraud detection model")
    parser.add_argument(
        "--model-type",
        choices=["logistic", "random_forest"],
        default="random_forest",
        help="Type of model to train"
    )
    parser.add_argument(
        "--test-size",
        type=float,
        default=0.2,
        help="Test set size (default: 0.2)"
    )

    args = parser.parse_args()

    logger.info("🤖 Starting fraud detection model training...")

    # Setup MLflow
    setup_mlflow()

    # Load data
    X, y, feature_columns = load_training_data()

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=args.test_size, random_state=42, stratify=y
    )

    logger.info(f"Training set size: {len(X_train)}")
    logger.info(f"Test set size: {len(X_test)}")

    # Train model
    model, scaler, metrics = train_model(
        X_train, X_test, y_train, y_test,
        model_type=args.model_type
    )

    # Create model metadata
    create_model_metadata()

    logger.info("✅ Model training completed successfully!")
    logger.info("🔗 View results in MLflow UI: http://localhost:5000")

if __name__ == "__main__":
    main()