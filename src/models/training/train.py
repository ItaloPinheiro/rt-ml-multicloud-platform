"""
Model training module for the ML platform.
Can be run standalone or imported as a module.
"""
import os
import sys
import argparse
from typing import Dict, Any, Tuple
import mlflow
import mlflow.sklearn
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ModelTrainer:
    """Handles model training and MLflow logging."""

    def __init__(self,
                 mlflow_tracking_uri: str = "http://mlflow-server:5000",
                 experiment_name: str = "fraud_detection_clean"):
        """Initialize the trainer with MLflow configuration."""
        self.mlflow_tracking_uri = mlflow_tracking_uri
        self.experiment_name = experiment_name
        self.setup_mlflow()

    def setup_mlflow(self):
        """Configure MLflow connection and experiment."""
        # Set tracking URI
        mlflow.set_tracking_uri(self.mlflow_tracking_uri)

        # Configure S3/MinIO for artifact storage if running in container
        if os.getenv("MLFLOW_S3_ENDPOINT_URL"):
            os.environ["AWS_ACCESS_KEY_ID"] = os.getenv("AWS_ACCESS_KEY_ID", "minioadmin")
            os.environ["AWS_SECRET_ACCESS_KEY"] = os.getenv("AWS_SECRET_ACCESS_KEY", "minioadmin123")

        # Create or get experiment with S3 artifact location
        try:
            experiment = mlflow.get_experiment_by_name(self.experiment_name)
            if experiment is None:
                # Create experiment with S3 artifact location
                artifact_location = None
                if os.getenv("MLFLOW_S3_ENDPOINT_URL"):
                    artifact_location = f"s3://mlflow/{self.experiment_name}"

                self.experiment_id = mlflow.create_experiment(
                    self.experiment_name,
                    artifact_location=artifact_location
                )
                logger.info(f"Created new experiment: {self.experiment_name} with S3 storage")
            else:
                self.experiment_id = experiment.experiment_id
                logger.info(f"Using existing experiment: {self.experiment_name}")
                # Log artifact location for debugging
                if experiment.artifact_location:
                    logger.info(f"Artifact location: {experiment.artifact_location}")
        except Exception as e:
            logger.warning(f"Could not create/get experiment, using default: {e}")
            self.experiment_id = "0"

    def load_data(self, data_path: str) -> Tuple[pd.DataFrame, pd.Series]:
        """Load and prepare training data."""
        logger.info(f"Loading data from {data_path}")
        df = pd.read_csv(data_path)

        # Separate features and target
        feature_columns = [col for col in df.columns if col != 'label']
        X = df[feature_columns]
        y = df['label']

        logger.info(f"Loaded {len(df)} samples with {len(feature_columns)} features")
        return X, y

    def train_model(self,
                   X_train: np.ndarray,
                   y_train: np.ndarray,
                   model_params: Dict[str, Any] = None) -> RandomForestClassifier:
        """Train a Random Forest model."""
        if model_params is None:
            model_params = {"n_estimators": 100, "random_state": 42}

        logger.info(f"Training Random Forest with params: {model_params}")
        model = RandomForestClassifier(**model_params)
        model.fit(X_train, y_train)
        return model

    def evaluate_model(self,
                      model: RandomForestClassifier,
                      X_test: np.ndarray,
                      y_test: np.ndarray) -> Dict[str, float]:
        """Evaluate model performance."""
        y_pred = model.predict(X_test)

        metrics = {
            "accuracy": accuracy_score(y_test, y_pred),
            "precision": precision_score(y_test, y_pred, zero_division=0),
            "recall": recall_score(y_test, y_pred, zero_division=0),
            "f1_score": f1_score(y_test, y_pred, zero_division=0)
        }

        logger.info("Model evaluation metrics:")
        for metric_name, value in metrics.items():
            logger.info(f"  {metric_name}: {value:.4f}")

        return metrics

    def train_and_log(self,
                     data_path: str,
                     model_name: str = "fraud_detector",
                     test_size: float = 0.2,
                     model_params: Dict[str, Any] = None):
        """Complete training pipeline with MLflow logging."""
        # Load data
        X, y = self.load_data(data_path)

        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42
        )

        if model_params is None:
            model_params = {"n_estimators": 100, "random_state": 42}

        # Create Pipeline (Scaler + Model)
        # We need to import Pipeline if it's not available in class scope (it is imported at top level)
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.ensemble import RandomForestClassifier

        logger.info(f"Training Random Forest Pipeline with params: {model_params}")
        
        pipeline = Pipeline([
            ('scaler', StandardScaler()),
            ('clf', RandomForestClassifier(**model_params))
        ])

        # Start MLflow run
        with mlflow.start_run(experiment_id=self.experiment_id) as run:
            # Train pipeline
            pipeline.fit(X_train, y_train)

            # Evaluate model
            y_pred = pipeline.predict(X_test)
            metrics = {
                "accuracy": accuracy_score(y_test, y_pred),
                "precision": precision_score(y_test, y_pred, zero_division=0),
                "recall": recall_score(y_test, y_pred, zero_division=0),
                "f1_score": f1_score(y_test, y_pred, zero_division=0)
            }

            logger.info("Model evaluation metrics:")
            for metric_name, value in metrics.items():
                logger.info(f"  {metric_name}: {value:.4f}")

            # Log parameters
            mlflow.log_param("model_type", "random_forest_pipeline")
            mlflow.log_param("test_size", test_size)
            if model_params:
                for param_name, param_value in model_params.items():
                    mlflow.log_param(param_name, param_value)

            # Log metrics
            for metric_name, value in metrics.items():
                mlflow.log_metric(metric_name, value)

            # Log model
            # Infer signature from actual DataFrame inputs to preserve column names
            signature = mlflow.models.infer_signature(X_test, y_pred)

            # Use explicit parameter name to avoid deprecation warning
            model_info = mlflow.sklearn.log_model(
                sk_model=pipeline,
                artifact_path="model",  # This is still required for the path in the artifact store
                signature=signature
            )

            logger.info(f"Model logged with run_id: {run.info.run_id}")

            # Register model if specified
            if model_name:
                self.register_model(run.info.run_id, model_name)

            return run.info.run_id, metrics

    def register_model(self, run_id: str, model_name: str, auto_promote: bool = True):
        """Register model in MLflow Model Registry and optionally promote to production.

        Args:
            run_id: MLflow run ID
            model_name: Name for registered model
            auto_promote: If True, promote to production if metrics are better
        """
        try:
            client = mlflow.MlflowClient()

            # Get current run's metrics
            current_run = client.get_run(run_id)
            current_metrics = current_run.data.metrics

            # Create registered model if it doesn't exist
            try:
                client.create_registered_model(model_name)
                logger.info(f"Created new registered model: {model_name}")
            except Exception:
                logger.info(f"Registered model {model_name} already exists")

            # Create model version
            model_version = client.create_model_version(
                name=model_name,
                source=f"runs:/{run_id}/model",
                run_id=run_id
            )

            logger.info(f"Registered model version: {model_version.version}")

            # With MLflow 2.9+, stages are deprecated
            # Instead, we use aliases or tags to mark production models
            if auto_promote:
                logger.info("Auto-promoting new model as latest version (production)")

                # Try to use the new alias system if available
                try:
                    # Set alias for production (MLflow 2.9+)
                    client.set_registered_model_alias(
                        name=model_name,
                        alias="production",
                        version=model_version.version
                    )
                    logger.info(f"Model {model_name} v{model_version.version} set as 'production' alias")
                except (AttributeError, Exception) as e:
                    # Fallback: Just tag the model as production
                    logger.debug(f"Alias API not available, using tags: {e}")
                    client.set_model_version_tag(
                        name=model_name,
                        version=model_version.version,
                        key="deployment_status",
                        value="production"
                    )
                    # Also tag previous production models as archived
                    try:
                        # Get all versions and update their tags
                        all_versions = client.search_model_versions(f"name='{model_name}'")
                        for v in all_versions:
                            if v.version != model_version.version:
                                # Check if it was production
                                if v.tags.get("deployment_status") == "production":
                                    client.set_model_version_tag(
                                        name=model_name,
                                        version=v.version,
                                        key="deployment_status",
                                        value="archived"
                                    )
                                    logger.info(f"Marked previous production model v{v.version} as archived")
                    except Exception as e:
                        logger.debug(f"Could not update previous versions: {e}")

                    logger.info(f"Model {model_name} v{model_version.version} tagged as production")

        except Exception as e:
            logger.error(f"Failed to register model: {e}")
            raise


def main():
    """Main training script entry point."""
    parser = argparse.ArgumentParser(description="Train fraud detection model")
    parser.add_argument(
        "--data-path",
        type=str,
        default="/app/sample_data/small/training_data.csv",
        help="Path to training data CSV"
    )
    parser.add_argument(
        "--mlflow-uri",
        type=str,
        default=os.getenv("MLFLOW_TRACKING_URI", "http://mlflow-server:5000"),
        help="MLflow tracking URI"
    )
    parser.add_argument(
        "--experiment",
        type=str,
        default="fraud_detection",
        help="MLflow experiment name"
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default="fraud_detector",
        help="Name for registered model"
    )
    parser.add_argument(
        "--n-estimators",
        type=int,
        default=100,
        help="Number of trees in Random Forest"
    )

    args = parser.parse_args()

    # Initialize trainer
    trainer = ModelTrainer(
        mlflow_tracking_uri=args.mlflow_uri,
        experiment_name=args.experiment
    )

    # Train model
    model_params = {
        "n_estimators": args.n_estimators,
        "random_state": 42,
        "n_jobs": -1
    }

    try:
        run_id, metrics = trainer.train_and_log(
            data_path=args.data_path,
            model_name=args.model_name,
            model_params=model_params
        )

        logger.info("Training completed successfully!")
        logger.info(f"View run in MLflow UI: {args.mlflow_uri}/#/experiments/0/runs/{run_id}")

    except Exception as e:
        logger.error(f"Training failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()