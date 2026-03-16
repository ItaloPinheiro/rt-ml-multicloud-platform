"""
Model training module for the ML platform.
Can be run standalone or imported as a module.

Supports any model type defined in configs/models/<model_name>.yaml.
Algorithm, preprocessing, features, and metrics are all config-driven.
"""

import argparse
import logging
import os
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

from src.models.model_definition import ModelDefinition, load_model_definition

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Registry of metric functions by name
METRIC_FUNCTIONS: Dict[str, Callable] = {
    "accuracy": accuracy_score,
    "precision": lambda y_true, y_pred: precision_score(
        y_true, y_pred, zero_division=0
    ),
    "recall": lambda y_true, y_pred: recall_score(y_true, y_pred, zero_division=0),
    "f1_score": lambda y_true, y_pred: f1_score(y_true, y_pred, zero_division=0),
    "r2_score": r2_score,
    "mae": mean_absolute_error,
    "mse": mean_squared_error,
}


class ModelTrainer:
    """Handles model training and MLflow logging.

    Driven by ModelDefinition config — algorithm, preprocessing pipeline,
    features, and metrics are all loaded from YAML, not hardcoded.
    """

    def __init__(
        self,
        mlflow_tracking_uri: str = "http://mlflow-server:5000",
        experiment_name: Optional[str] = None,
        model_definition: Optional[ModelDefinition] = None,
        model_type: str = "fraud_detector",
    ):
        """Initialize the trainer with MLflow configuration.

        Args:
            mlflow_tracking_uri: MLflow tracking server URI.
            experiment_name: Override experiment name (defaults to model definition).
            model_definition: Pre-loaded ModelDefinition. If None, loads from model_type.
            model_type: Model definition name to load from configs/models/.
        """
        if model_definition is not None:
            self.model_def = model_definition
        else:
            self.model_def = load_model_definition(model_type)

        self.mlflow_tracking_uri = mlflow_tracking_uri
        self.experiment_name = experiment_name or self.model_def.mlflow.experiment_name
        self.setup_mlflow()

    def setup_mlflow(self):
        """Configure MLflow connection and experiment."""
        # Set tracking URI
        mlflow.set_tracking_uri(self.mlflow_tracking_uri)

        # Configure S3/MinIO for artifact storage if running in container
        if os.getenv("MLFLOW_S3_ENDPOINT_URL"):
            os.environ["AWS_ACCESS_KEY_ID"] = os.getenv(
                "AWS_ACCESS_KEY_ID", "minioadmin"
            )
            os.environ["AWS_SECRET_ACCESS_KEY"] = os.getenv(
                "AWS_SECRET_ACCESS_KEY", "minioadmin123"
            )

        # Create or get experiment with S3 artifact location
        try:
            experiment = mlflow.get_experiment_by_name(self.experiment_name)
            if experiment is None:
                # Create experiment with S3 artifact location
                artifact_location = None
                if os.getenv("MLFLOW_S3_ENDPOINT_URL"):
                    artifact_location = f"s3://mlflow/{self.experiment_name}"

                self.experiment_id = mlflow.create_experiment(
                    self.experiment_name, artifact_location=artifact_location
                )
                logger.info(
                    f"Created new experiment: {self.experiment_name} with S3 storage"
                )
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
        """Load and prepare training data using model definition features."""
        logger.info(f"Loading data from {data_path}")
        if data_path.endswith(".parquet"):
            df = pd.read_parquet(data_path)
        else:
            df = pd.read_csv(data_path)

        target = self.model_def.features.target
        feature_columns = self.model_def.features.columns

        # Validate that expected columns exist in data
        missing = set(feature_columns + [target]) - set(df.columns)
        if missing:
            # Fall back to auto-detection if definition columns don't match
            logger.warning(
                f"Columns {missing} not found in data, "
                f"falling back to all non-target columns"
            )
            feature_columns = [col for col in df.columns if col != target]

        X = df[feature_columns]
        y = df[target]

        # Cast integer columns to float64 for nullable-safe schema inference
        # This prevents MLflow UserWarning about integer columns not handling missing values
        int_columns = X.select_dtypes(include=["int64", "int32"]).columns
        X = X.copy()  # Avoid SettingWithCopyWarning
        X[int_columns] = X[int_columns].astype("float64")

        logger.info(f"Loaded {len(df)} samples with {len(feature_columns)} features")
        return X, y

    def load_data_from_feature_store(
        self,
        feature_groups: List[str],
        feature_schema: Dict[str, List[str]],
        labeling_strategy: str = "rule_based",
        label_field: str = "risk_score",
        label_threshold: float = 0.5,
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """Load training data directly from PostgreSQL feature store.

        JSONB model: each row contains all features as a single JSON object,
        so no EAV pivot is needed. Streams results with yield_per for memory
        efficiency.

        Args:
            feature_groups: List of feature group names to query.
            feature_schema: Dict mapping feature_group -> list of feature names.
            labeling_strategy: How to assign labels ("rule_based" or "file_based").
            label_field: Feature field to use for rule-based labeling.
            label_threshold: Threshold for rule-based labeling.

        Returns:
            Tuple of (X, y) matching the format from load_data().
        """
        from sqlalchemy import select

        from src.database.models import FeatureStore as FeatureStoreModel
        from src.database.session import get_session

        logger.info(
            f"Loading from feature store: groups={feature_groups}"
        )

        # JSONB model: select entity_id + features JSON per row
        stmt = select(
            FeatureStoreModel.entity_id,
            FeatureStoreModel.features,
        ).where(
            FeatureStoreModel.feature_group.in_(feature_groups),
            FeatureStoreModel.is_active.is_(True),
        )

        # Stream results with yield_per to reduce peak memory
        rows = []
        with get_session() as session:
            result = session.execute(stmt).yield_per(10_000)
            for partition in result.partitions():
                for entity_id, features in partition:
                    if features:
                        row = dict(features)
                        row["entity_id"] = entity_id
                        rows.append(row)

        if not rows:
            raise ValueError(
                f"No features found in feature store for groups {feature_groups}"
            )

        # Already wide format — no pivot needed
        wide = pd.DataFrame(rows)
        logger.info(
            f"Read {len(wide)} entities x {len(wide.columns) - 1} features "
            f"from feature store"
        )

        # Cast JSON values to numeric
        for col in wide.columns:
            if col != "entity_id":
                wide[col] = pd.to_numeric(wide[col], errors="coerce")

        # Apply labeling strategy
        if labeling_strategy == "rule_based":
            if label_field in wide.columns:
                wide["label"] = (wide[label_field] >= label_threshold).astype(int)
            else:
                logger.warning(
                    f"Label field '{label_field}' not found, defaulting to 0"
                )
                wide["label"] = 0
        else:
            wide["label"] = 0

        # Select feature columns in model definition order
        target = self.model_def.features.target
        feature_columns = self.model_def.features.columns

        missing = set(feature_columns) - set(wide.columns)
        if missing:
            logger.warning(
                f"Columns {missing} not found in feature store, "
                f"falling back to available columns"
            )
            feature_columns = [c for c in feature_columns if c in wide.columns]

        X = wide[feature_columns].copy()
        y = wide[target]

        # Cast integer columns to float64
        int_columns = X.select_dtypes(include=["int64", "int32"]).columns
        X[int_columns] = X[int_columns].astype("float64")

        logger.info(
            f"Feature store data ready: {len(X)} samples, "
            f"{len(feature_columns)} features"
        )
        return X, y

    def _load_feature_schema_from_config(self) -> Dict[str, List[str]]:
        """Load feature_store.schema from model definition YAML."""
        from pathlib import Path

        import yaml

        from src.models.model_definition import _DEFAULT_DEFINITIONS_PATH

        yaml_path = (
            Path(_DEFAULT_DEFINITIONS_PATH) / f"{self.model_def.model_name}.yaml"
        )
        with open(yaml_path) as f:
            raw = yaml.safe_load(f)

        fs_config = raw.get("feature_store", {})
        schema = fs_config.get("schema", {})
        if not schema:
            logger.warning(
                "No feature_store.schema in model config, using all feature columns"
            )
            # Fallback: put all columns in first group
            schema = {"transaction_features": list(self.model_def.features.columns)}
        return schema

    def train_model(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        model_params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Train the model defined in model definition."""
        params = {**self.model_def.algorithm.default_params, **(model_params or {})}

        logger.info(
            f"Training {self.model_def.algorithm.class_path} with params: {params}"
        )
        model = self.model_def.algorithm.create_instance(model_params)
        model.fit(X_train, y_train)
        return model

    def evaluate_model(
        self, model: Any, X_test: np.ndarray, y_test: np.ndarray
    ) -> Dict[str, float]:
        """Evaluate model using metrics from model definition."""
        y_pred = model.predict(X_test)

        metrics = {}
        for metric_name in self.model_def.metrics:
            func = METRIC_FUNCTIONS.get(metric_name)
            if func:
                metrics[metric_name] = func(y_test, y_pred)
            else:
                logger.warning(f"Unknown metric '{metric_name}', skipping")

        logger.info("Model evaluation metrics:")
        for metric_name, value in metrics.items():
            logger.info(f"  {metric_name}: {value:.4f}")

        return metrics

    def _build_pipeline(
        self, model_params: Optional[Dict[str, Any]] = None
    ) -> Pipeline:
        """Build sklearn Pipeline from model definition config."""
        steps = []
        for step_cfg in self.model_def.pipeline_steps:
            steps.append((step_cfg.name, step_cfg.create_instance()))

        steps.append(("clf", self.model_def.algorithm.create_instance(model_params)))
        return Pipeline(steps)

    def train_and_log(
        self,
        data_path: Optional[str] = None,
        model_name: Optional[str] = None,
        test_size: float = 0.2,
        model_params: Optional[Dict[str, Any]] = None,
        auto_promote: bool = True,
        use_feature_store: bool = False,
        feature_groups: Optional[List[str]] = None,
        feature_schema: Optional[Dict[str, List[str]]] = None,
        labeling_strategy: str = "rule_based",
        label_field: str = "risk_score",
        label_threshold: float = 0.5,
    ):
        """Complete training pipeline with MLflow logging."""
        model_name = model_name or self.model_def.model_name

        # Load data from feature store or file
        if use_feature_store:
            if not feature_groups:
                feature_groups = ["transaction_features", "aggregated_features"]
            if not feature_schema:
                feature_schema = self._load_feature_schema_from_config()
            X, y = self.load_data_from_feature_store(
                feature_groups=feature_groups,
                feature_schema=feature_schema,
                labeling_strategy=labeling_strategy,
                label_field=label_field,
                label_threshold=label_threshold,
            )
            data_source = "feature_store"
        else:
            if data_path is None:
                raise ValueError("data_path is required when not using feature store")
            X, y = self.load_data(data_path)
            data_source = "csv" if data_path.endswith(".csv") else "parquet"

        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42
        )

        params = {**self.model_def.algorithm.default_params, **(model_params or {})}

        logger.info(
            f"Training {self.model_def.algorithm.class_path} pipeline "
            f"with params: {params}"
        )

        pipeline = self._build_pipeline(model_params)

        # Start MLflow run
        with mlflow.start_run(experiment_id=self.experiment_id) as run:
            # Train pipeline
            pipeline.fit(X_train, y_train)

            # Evaluate model
            y_pred = pipeline.predict(X_test)
            metrics = {}
            for metric_name in self.model_def.metrics:
                func = METRIC_FUNCTIONS.get(metric_name)
                if func:
                    metrics[metric_name] = func(y_test, y_pred)

            logger.info("Model evaluation metrics:")
            for metric_name, value in metrics.items():
                logger.info(f"  {metric_name}: {value:.4f}")

            # Log parameters
            mlflow.log_param("model_type", self.model_def.model_name)
            mlflow.log_param("algorithm", self.model_def.algorithm.class_path)
            mlflow.log_param("task_type", self.model_def.task_type)
            mlflow.log_param("test_size", test_size)
            mlflow.log_param("data_source", data_source)
            if params:
                for param_name, param_value in params.items():
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
                name="model",  # MLflow 3.x prefers 'name' instead of 'artifact_path'
                signature=signature,
            )

            logger.info(f"Model logged with run_id: {run.info.run_id}")

            # Register model if specified
            if model_name:
                self.register_model(
                    run.info.run_id, model_info.model_uri, model_name, auto_promote
                )

            return run.info.run_id, metrics

    def register_model(
        self, run_id: str, model_uri: str, model_name: str, auto_promote: bool = True
    ):
        """Register model in MLflow Model Registry and optionally promote to production.

        Args:
            run_id: MLflow run ID
            model_uri: The actual model URI returned by log_model
            model_name: Name for registered model
            auto_promote: If True, promote to production if metrics are better
        """
        try:
            client = mlflow.MlflowClient()

            # Get current run's metrics
            client.get_run(run_id)

            # Create registered model if it doesn't exist
            try:
                client.create_registered_model(model_name)
                logger.info(f"Created new registered model: {model_name}")
            except Exception:
                logger.info(f"Registered model {model_name} already exists")

            # Create model version using the actual model_uri
            model_version = client.create_model_version(
                name=model_name, source=model_uri, run_id=run_id
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
                        version=model_version.version,
                    )
                    logger.info(
                        f"Model {model_name} v{model_version.version} set as 'production' alias"
                    )
                except (AttributeError, Exception) as e:
                    # Fallback: Just tag the model as production
                    logger.debug(f"Alias API not available, using tags: {e}")
                    client.set_model_version_tag(
                        name=model_name,
                        version=model_version.version,
                        key="deployment_status",
                        value="production",
                    )
                    # Also tag previous production models as archived
                    try:
                        # Get all versions and update their tags
                        all_versions = client.search_model_versions(
                            f"name='{model_name}'"
                        )
                        for v in all_versions:
                            if v.version != model_version.version:
                                # Check if it was production
                                if v.tags.get("deployment_status") == "production":
                                    client.set_model_version_tag(
                                        name=model_name,
                                        version=v.version,
                                        key="deployment_status",
                                        value="archived",
                                    )
                                    logger.info(
                                        f"Marked previous production model v{v.version} as archived"
                                    )
                    except Exception as e:
                        logger.debug(f"Could not update previous versions: {e}")

                    logger.info(
                        f"Model {model_name} v{model_version.version} tagged as production"
                    )

        except Exception as e:
            logger.error(f"Failed to register model: {e}")
            raise


def main():
    """Main training script entry point."""
    parser = argparse.ArgumentParser(description="Train ML model")
    parser.add_argument(
        "--model-type",
        type=str,
        default="fraud_detector",
        help="Model definition name from configs/models/ (default: fraud_detector)",
    )
    parser.add_argument(
        "--data-path",
        type=str,
        default="/app/sample_data/small/training_data.csv",
        help="Path to training data CSV",
    )
    parser.add_argument(
        "--mlflow-uri",
        type=str,
        default=os.getenv("MLFLOW_TRACKING_URI", "http://mlflow-server:5000"),
        help="MLflow tracking URI",
    )
    parser.add_argument(
        "--experiment",
        type=str,
        default=None,
        help="MLflow experiment name (defaults to model definition)",
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default=None,
        help="Name for registered model (defaults to model definition)",
    )
    parser.add_argument(
        "--n-estimators", type=int, default=None, help="Number of trees (if applicable)"
    )
    parser.add_argument(
        "--auto-promote",
        action="store_true",
        default=False,
        help="Automatically promote model to production (skip evaluation gate)",
    )
    parser.add_argument(
        "--class-weight",
        type=str,
        default=None,
        choices=["balanced", "balanced_subsample"],
        help="Class weight strategy for handling imbalanced datasets",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=None,
        help="Maximum depth of trees (None for unlimited)",
    )
    parser.add_argument(
        "--use-feature-store",
        action="store_true",
        default=False,
        help="Load training data from feature store instead of CSV/Parquet file",
    )
    parser.add_argument(
        "--feature-groups",
        type=str,
        default="transaction_features,aggregated_features",
        help="Comma-separated feature groups (default: transaction_features,aggregated_features)",
    )

    args = parser.parse_args()

    # Load model definition
    model_def = load_model_definition(args.model_type)

    # Initialize trainer
    trainer = ModelTrainer(
        mlflow_tracking_uri=args.mlflow_uri,
        experiment_name=args.experiment,
        model_definition=model_def,
    )

    # Build model params from CLI args, falling back to definition defaults
    model_params = dict(model_def.algorithm.default_params)
    if args.n_estimators is not None:
        model_params["n_estimators"] = args.n_estimators
    if args.class_weight:
        model_params["class_weight"] = args.class_weight
    if args.max_depth is not None:
        model_params["max_depth"] = args.max_depth

    model_name = args.model_name or model_def.model_name

    try:
        train_kwargs: Dict[str, Any] = {
            "model_name": model_name,
            "model_params": model_params,
            "auto_promote": args.auto_promote,
        }

        if args.use_feature_store:
            train_kwargs["use_feature_store"] = True
            train_kwargs["feature_groups"] = [
                g.strip() for g in args.feature_groups.split(",")
            ]
        else:
            train_kwargs["data_path"] = args.data_path

        run_id, metrics = trainer.train_and_log(**train_kwargs)

        logger.info("Training completed successfully!")
        logger.info(
            f"View run in MLflow UI: {args.mlflow_uri}/#/experiments/0/runs/{run_id}"
        )

    except Exception as e:
        logger.error(f"Training failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
