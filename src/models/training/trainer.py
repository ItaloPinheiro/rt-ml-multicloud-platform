"""MLflow-integrated model training framework.

This module provides a comprehensive model training framework with MLflow
tracking, experiment management, and model registry integration.
"""

import os
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    import mlflow
    import mlflow.lightgbm
    import mlflow.sklearn
    import mlflow.xgboost
    from mlflow.entities import ViewType
    from mlflow.tracking import MlflowClient
except ImportError:
    mlflow = None
    MlflowClient = None

try:
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.linear_model import LinearRegression, LogisticRegression
    from sklearn.metrics import (
        accuracy_score,
        classification_report,
        confusion_matrix,
        f1_score,
        mean_absolute_error,
        mean_squared_error,
        precision_score,
        r2_score,
        recall_score,
        roc_auc_score,
    )
    from sklearn.model_selection import (
        GridSearchCV,
        RandomizedSearchCV,
        cross_val_score,
        train_test_split,
    )
    from sklearn.preprocessing import LabelEncoder, StandardScaler
except ImportError:
    pass

try:
    import xgboost as xgb
except ImportError:
    xgb = None

try:
    import lightgbm as lgb
except ImportError:
    lgb = None

import structlog

logger = structlog.get_logger()


class ModelTrainer:
    """MLflow-integrated model trainer.

    This class provides a comprehensive framework for training ML models
    with automatic experiment tracking, hyperparameter tuning, and model registration.
    """

    def __init__(
        self,
        mlflow_uri: str,
        experiment_name: str,
        model_registry_uri: Optional[str] = None,
    ):
        """Initialize model trainer.

        Args:
            mlflow_uri: MLflow tracking server URI
            experiment_name: Name of the MLflow experiment
            model_registry_uri: Model registry URI (optional, uses tracking URI by default)

        Raises:
            ImportError: If required dependencies are not installed
        """
        if mlflow is None:
            raise ImportError(
                "mlflow is required for model training. "
                "Install with: pip install mlflow"
            )

        self.mlflow_uri = mlflow_uri
        self.experiment_name = experiment_name
        self.model_registry_uri = model_registry_uri or mlflow_uri

        # Configure MLflow
        mlflow.set_tracking_uri(mlflow_uri)
        if model_registry_uri:
            mlflow.set_registry_uri(model_registry_uri)

        # Create or get experiment
        try:
            self.experiment_id = mlflow.create_experiment(experiment_name)
            logger.info(
                "Created new MLflow experiment", experiment_name=experiment_name
            )
        except:
            experiment = mlflow.get_experiment_by_name(experiment_name)
            self.experiment_id = experiment.experiment_id
            logger.info(
                "Using existing MLflow experiment", experiment_name=experiment_name
            )

        mlflow.set_experiment(experiment_name)

        self.client = MlflowClient(mlflow_uri)
        self.logger = logger.bind(
            component="ModelTrainer", experiment=experiment_name, mlflow_uri=mlflow_uri
        )

    def train_classification_model(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        model_type: str = "xgboost",
        test_size: float = 0.2,
        validation_size: float = 0.1,
        hyperparameters: Optional[Dict[str, Any]] = None,
        cv_folds: int = 5,
        auto_tune: bool = False,
        tune_trials: int = 50,
        run_name: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
    ) -> Tuple[Any, Dict[str, float], str]:
        """Train a classification model with comprehensive tracking.

        Args:
            X: Feature matrix
            y: Target vector
            model_type: Type of model to train
            test_size: Proportion of data for testing
            validation_size: Proportion of data for validation
            hyperparameters: Model hyperparameters
            cv_folds: Number of cross-validation folds
            auto_tune: Whether to perform hyperparameter tuning
            tune_trials: Number of tuning trials
            run_name: Custom run name
            tags: Additional tags for the run

        Returns:
            Tuple of (trained_model, metrics, run_id)
        """
        # Generate run name if not provided
        if run_name is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_name = f"{model_type}_classification_{timestamp}"

        with mlflow.start_run(run_name=run_name, tags=tags) as run:
            run_id = run.info.run_id
            self.logger.info("Started MLflow run", run_id=run_id, run_name=run_name)

            try:
                # Log dataset info
                mlflow.log_param("dataset_size", len(X))
                mlflow.log_param("n_features", X.shape[1])
                mlflow.log_param("n_classes", len(y.unique()))
                mlflow.log_param("model_type", model_type)
                mlflow.log_param("test_size", test_size)
                mlflow.log_param("validation_size", validation_size)

                # Split data
                X_temp, X_test, y_temp, y_test = train_test_split(
                    X, y, test_size=test_size, random_state=42, stratify=y
                )

                if validation_size > 0:
                    val_size_adjusted = validation_size / (1 - test_size)
                    X_train, X_val, y_train, y_val = train_test_split(
                        X_temp,
                        y_temp,
                        test_size=val_size_adjusted,
                        random_state=42,
                        stratify=y_temp,
                    )
                else:
                    X_train, X_val, y_train, y_val = X_temp, None, y_temp, None

                # Log data splits
                mlflow.log_param("train_size", len(X_train))
                mlflow.log_param("test_size", len(X_test))
                if X_val is not None:
                    mlflow.log_param("val_size", len(X_val))

                # Hyperparameter tuning if requested
                if auto_tune:
                    best_params = self._tune_hyperparameters(
                        X_train, y_train, model_type, tune_trials, cv_folds
                    )
                    hyperparameters = best_params

                # Train model
                model = self._train_model(X_train, y_train, model_type, hyperparameters)

                # Evaluate model
                metrics = self._evaluate_classification_model(
                    model, X_train, y_train, X_val, y_val, X_test, y_test, cv_folds
                )

                # Log metrics
                for metric_name, metric_value in metrics.items():
                    mlflow.log_metric(metric_name, metric_value)

                # Log feature importance if available
                self._log_feature_importance(model, X.columns)

                # Log model artifacts
                self._log_model_artifacts(model, model_type, X_train.columns.tolist())

                # Save model
                model_info = self._save_model(model, model_type, run_id)

                self.logger.info(
                    "Model training completed successfully",
                    model_type=model_type,
                    run_id=run_id,
                    test_accuracy=metrics.get("test_accuracy", 0),
                )

                return model, metrics, run_id

            except Exception as e:
                self.logger.error("Model training failed", error=str(e), run_id=run_id)
                mlflow.log_param("training_status", "failed")
                mlflow.log_param("error_message", str(e))
                raise

    def train_regression_model(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        model_type: str = "xgboost",
        test_size: float = 0.2,
        validation_size: float = 0.1,
        hyperparameters: Optional[Dict[str, Any]] = None,
        cv_folds: int = 5,
        auto_tune: bool = False,
        tune_trials: int = 50,
        run_name: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
    ) -> Tuple[Any, Dict[str, float], str]:
        """Train a regression model with comprehensive tracking.

        Args:
            X: Feature matrix
            y: Target vector
            model_type: Type of model to train
            test_size: Proportion of data for testing
            validation_size: Proportion of data for validation
            hyperparameters: Model hyperparameters
            cv_folds: Number of cross-validation folds
            auto_tune: Whether to perform hyperparameter tuning
            tune_trials: Number of tuning trials
            run_name: Custom run name
            tags: Additional tags for the run

        Returns:
            Tuple of (trained_model, metrics, run_id)
        """
        # Similar implementation to classification but with regression metrics
        if run_name is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_name = f"{model_type}_regression_{timestamp}"

        with mlflow.start_run(run_name=run_name, tags=tags) as run:
            run_id = run.info.run_id

            # Log parameters
            mlflow.log_param("dataset_size", len(X))
            mlflow.log_param("n_features", X.shape[1])
            mlflow.log_param("model_type", model_type)
            mlflow.log_param("task_type", "regression")

            # Split data
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=test_size, random_state=42
            )

            # Train model
            model = self._train_model(
                X_train, y_train, model_type, hyperparameters, task="regression"
            )

            # Evaluate model
            metrics = self._evaluate_regression_model(
                model, X_train, y_train, X_test, y_test, cv_folds
            )

            # Log metrics and artifacts
            for metric_name, metric_value in metrics.items():
                mlflow.log_metric(metric_name, metric_value)

            self._log_feature_importance(model, X.columns)
            self._log_model_artifacts(model, model_type, X_train.columns.tolist())
            model_info = self._save_model(model, model_type, run_id)

            return model, metrics, run_id

    def _train_model(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        model_type: str,
        hyperparameters: Optional[Dict[str, Any]] = None,
        task: str = "classification",
    ) -> Any:
        """Train a model of the specified type.

        Args:
            X_train: Training features
            y_train: Training targets
            model_type: Type of model to train
            hyperparameters: Model hyperparameters
            task: Task type (classification or regression)

        Returns:
            Trained model
        """
        hyperparameters = hyperparameters or {}

        if model_type == "xgboost":
            return self._train_xgboost(X_train, y_train, hyperparameters, task)
        elif model_type == "lightgbm":
            return self._train_lightgbm(X_train, y_train, hyperparameters, task)
        elif model_type == "random_forest":
            return self._train_random_forest(X_train, y_train, hyperparameters, task)
        elif model_type == "logistic_regression" and task == "classification":
            return self._train_logistic_regression(X_train, y_train, hyperparameters)
        elif model_type == "linear_regression" and task == "regression":
            return self._train_linear_regression(X_train, y_train, hyperparameters)
        else:
            raise ValueError(f"Unsupported model type: {model_type} for task: {task}")

    def _train_xgboost(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        hyperparameters: Dict[str, Any],
        task: str,
    ) -> Any:
        """Train XGBoost model."""
        if xgb is None:
            raise ImportError("xgboost is required for XGBoost training")

        if task == "classification":
            default_params = {
                "n_estimators": 100,
                "max_depth": 6,
                "learning_rate": 0.1,
                "objective": "binary:logistic",
                "eval_metric": "auc",
                "random_state": 42,
            }
            model_class = xgb.XGBClassifier
        else:
            default_params = {
                "n_estimators": 100,
                "max_depth": 6,
                "learning_rate": 0.1,
                "objective": "reg:squarederror",
                "eval_metric": "rmse",
                "random_state": 42,
            }
            model_class = xgb.XGBRegressor

        default_params.update(hyperparameters)

        # Log hyperparameters
        for key, value in default_params.items():
            mlflow.log_param(f"xgb_{key}", value)

        model = model_class(**default_params)
        model.fit(X_train, y_train)

        return model

    def _train_lightgbm(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        hyperparameters: Dict[str, Any],
        task: str,
    ) -> Any:
        """Train LightGBM model."""
        if lgb is None:
            raise ImportError("lightgbm is required for LightGBM training")

        if task == "classification":
            default_params = {
                "n_estimators": 100,
                "max_depth": -1,
                "learning_rate": 0.1,
                "objective": "binary",
                "metric": "auc",
                "random_state": 42,
                "verbose": -1,
            }
            model_class = lgb.LGBMClassifier
        else:
            default_params = {
                "n_estimators": 100,
                "max_depth": -1,
                "learning_rate": 0.1,
                "objective": "regression",
                "metric": "rmse",
                "random_state": 42,
                "verbose": -1,
            }
            model_class = lgb.LGBMRegressor

        default_params.update(hyperparameters)

        # Log hyperparameters
        for key, value in default_params.items():
            mlflow.log_param(f"lgb_{key}", value)

        model = model_class(**default_params)
        model.fit(X_train, y_train)

        return model

    def _train_random_forest(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        hyperparameters: Dict[str, Any],
        task: str,
    ) -> Any:
        """Train Random Forest model."""
        if task == "classification":
            default_params = {
                "n_estimators": 100,
                "max_depth": None,
                "random_state": 42,
            }
            model_class = RandomForestClassifier
        else:
            default_params = {
                "n_estimators": 100,
                "max_depth": None,
                "random_state": 42,
            }
            model_class = RandomForestRegressor

        default_params.update(hyperparameters)

        # Log hyperparameters
        for key, value in default_params.items():
            mlflow.log_param(f"rf_{key}", value)

        model = model_class(**default_params)
        model.fit(X_train, y_train)

        return model

    def _train_logistic_regression(
        self, X_train: pd.DataFrame, y_train: pd.Series, hyperparameters: Dict[str, Any]
    ) -> LogisticRegression:
        """Train Logistic Regression model."""
        default_params = {"random_state": 42, "max_iter": 1000}
        default_params.update(hyperparameters)

        # Log hyperparameters
        for key, value in default_params.items():
            mlflow.log_param(f"lr_{key}", value)

        model = LogisticRegression(**default_params)
        model.fit(X_train, y_train)

        return model

    def _train_linear_regression(
        self, X_train: pd.DataFrame, y_train: pd.Series, hyperparameters: Dict[str, Any]
    ) -> LinearRegression:
        """Train Linear Regression model."""
        default_params = {}
        default_params.update(hyperparameters)

        # Log hyperparameters
        for key, value in default_params.items():
            mlflow.log_param(f"linreg_{key}", value)

        model = LinearRegression(**default_params)
        model.fit(X_train, y_train)

        return model

    def _evaluate_classification_model(
        self,
        model: Any,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame],
        y_val: Optional[pd.Series],
        X_test: pd.DataFrame,
        y_test: pd.Series,
        cv_folds: int,
    ) -> Dict[str, float]:
        """Evaluate classification model performance."""
        metrics = {}

        # Training metrics
        y_train_pred = model.predict(X_train)
        y_train_pred_proba = (
            model.predict_proba(X_train)[:, 1]
            if hasattr(model, "predict_proba")
            else None
        )

        metrics["train_accuracy"] = accuracy_score(y_train, y_train_pred)
        metrics["train_precision"] = precision_score(
            y_train, y_train_pred, average="weighted"
        )
        metrics["train_recall"] = recall_score(
            y_train, y_train_pred, average="weighted"
        )
        metrics["train_f1"] = f1_score(y_train, y_train_pred, average="weighted")

        if y_train_pred_proba is not None:
            metrics["train_auc"] = roc_auc_score(y_train, y_train_pred_proba)

        # Validation metrics
        if X_val is not None and y_val is not None:
            y_val_pred = model.predict(X_val)
            y_val_pred_proba = (
                model.predict_proba(X_val)[:, 1]
                if hasattr(model, "predict_proba")
                else None
            )

            metrics["val_accuracy"] = accuracy_score(y_val, y_val_pred)
            metrics["val_precision"] = precision_score(
                y_val, y_val_pred, average="weighted"
            )
            metrics["val_recall"] = recall_score(y_val, y_val_pred, average="weighted")
            metrics["val_f1"] = f1_score(y_val, y_val_pred, average="weighted")

            if y_val_pred_proba is not None:
                metrics["val_auc"] = roc_auc_score(y_val, y_val_pred_proba)

        # Test metrics
        y_test_pred = model.predict(X_test)
        y_test_pred_proba = (
            model.predict_proba(X_test)[:, 1]
            if hasattr(model, "predict_proba")
            else None
        )

        metrics["test_accuracy"] = accuracy_score(y_test, y_test_pred)
        metrics["test_precision"] = precision_score(
            y_test, y_test_pred, average="weighted"
        )
        metrics["test_recall"] = recall_score(y_test, y_test_pred, average="weighted")
        metrics["test_f1"] = f1_score(y_test, y_test_pred, average="weighted")

        if y_test_pred_proba is not None:
            metrics["test_auc"] = roc_auc_score(y_test, y_test_pred_proba)

        # Cross-validation
        if cv_folds > 1:
            cv_scores = cross_val_score(
                model, X_train, y_train, cv=cv_folds, scoring="accuracy"
            )
            metrics["cv_accuracy_mean"] = cv_scores.mean()
            metrics["cv_accuracy_std"] = cv_scores.std()

        return metrics

    def _evaluate_regression_model(
        self,
        model: Any,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_test: pd.DataFrame,
        y_test: pd.Series,
        cv_folds: int,
    ) -> Dict[str, float]:
        """Evaluate regression model performance."""
        metrics = {}

        # Training metrics
        y_train_pred = model.predict(X_train)
        metrics["train_mse"] = mean_squared_error(y_train, y_train_pred)
        metrics["train_rmse"] = np.sqrt(metrics["train_mse"])
        metrics["train_mae"] = mean_absolute_error(y_train, y_train_pred)
        metrics["train_r2"] = r2_score(y_train, y_train_pred)

        # Test metrics
        y_test_pred = model.predict(X_test)
        metrics["test_mse"] = mean_squared_error(y_test, y_test_pred)
        metrics["test_rmse"] = np.sqrt(metrics["test_mse"])
        metrics["test_mae"] = mean_absolute_error(y_test, y_test_pred)
        metrics["test_r2"] = r2_score(y_test, y_test_pred)

        # Cross-validation
        if cv_folds > 1:
            cv_scores = cross_val_score(
                model, X_train, y_train, cv=cv_folds, scoring="neg_mean_squared_error"
            )
            metrics["cv_mse_mean"] = -cv_scores.mean()
            metrics["cv_mse_std"] = cv_scores.std()

        return metrics

    def _log_feature_importance(self, model: Any, feature_names: List[str]) -> None:
        """Log feature importance if available."""
        if hasattr(model, "feature_importances_"):
            importance_df = pd.DataFrame(
                {"feature": feature_names, "importance": model.feature_importances_}
            ).sort_values("importance", ascending=False)

            # Log top 20 features
            for idx, row in importance_df.head(20).iterrows():
                mlflow.log_metric(
                    f"feature_importance_{row['feature']}", row["importance"]
                )

            # Save feature importance as artifact
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".csv", delete=False
            ) as f:
                importance_df.to_csv(f.name, index=False)
                mlflow.log_artifact(f.name, "feature_importance")
                os.unlink(f.name)

    def _log_model_artifacts(
        self, model: Any, model_type: str, feature_names: List[str]
    ) -> None:
        """Log model-related artifacts."""
        # Save feature names
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            import json

            json.dump(feature_names, f)
            mlflow.log_artifact(f.name, "model_metadata")
            os.unlink(f.name)

        # Log model parameters
        if hasattr(model, "get_params"):
            params = model.get_params()
            for key, value in params.items():
                mlflow.log_param(f"final_{key}", value)

    def _save_model(self, model: Any, model_type: str, run_id: str) -> Dict[str, Any]:
        """Save model to MLflow."""
        if model_type == "xgboost" and xgb is not None:
            model_info = mlflow.xgboost.log_model(model, "model")
        elif model_type == "lightgbm" and lgb is not None:
            model_info = mlflow.lightgbm.log_model(model, "model")
        else:
            model_info = mlflow.sklearn.log_model(model, "model")

        return model_info

    def _tune_hyperparameters(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        model_type: str,
        n_trials: int,
        cv_folds: int,
    ) -> Dict[str, Any]:
        """Perform hyperparameter tuning."""
        # Implementation would include hyperparameter search spaces
        # and optimization using GridSearchCV or RandomizedSearchCV
        # This is a simplified version

        self.logger.info(
            "Starting hyperparameter tuning", model_type=model_type, n_trials=n_trials
        )

        # Define search spaces based on model type
        if model_type == "xgboost":
            param_grid = {
                "n_estimators": [50, 100, 200],
                "max_depth": [3, 6, 9],
                "learning_rate": [0.01, 0.1, 0.2],
            }
            base_model = xgb.XGBClassifier(random_state=42)
        elif model_type == "random_forest":
            param_grid = {
                "n_estimators": [50, 100, 200],
                "max_depth": [None, 10, 20],
                "min_samples_split": [2, 5, 10],
            }
            base_model = RandomForestClassifier(random_state=42)
        else:
            return {}

        # Perform randomized search
        search = RandomizedSearchCV(
            base_model,
            param_grid,
            n_iter=min(n_trials, 20),  # Limit for demo
            cv=cv_folds,
            scoring="roc_auc",
            random_state=42,
            n_jobs=-1,
        )

        search.fit(X_train, y_train)

        # Log tuning results
        mlflow.log_param("tuning_best_score", search.best_score_)
        for key, value in search.best_params_.items():
            mlflow.log_param(f"tuned_{key}", value)

        self.logger.info(
            "Hyperparameter tuning completed", best_score=search.best_score_
        )

        return search.best_params_

    def load_model(
        self, model_name: str, version: str = "latest", stage: str = None
    ) -> Any:
        """Load model from MLflow registry.

        Args:
            model_name: Name of the registered model
            version: Model version or "latest"
            stage: Model stage (Staging, Production, etc.)

        Returns:
            Loaded model
        """
        try:
            if stage:
                model_uri = f"models:/{model_name}/{stage}"
            elif version == "latest":
                model_uri = f"models:/{model_name}/latest"
            else:
                model_uri = f"models:/{model_name}/{version}"

            model = mlflow.pyfunc.load_model(model_uri)

            self.logger.info(
                "Model loaded successfully",
                model_name=model_name,
                version=version,
                stage=stage,
            )

            return model

        except Exception as e:
            self.logger.error(
                "Failed to load model",
                model_name=model_name,
                version=version,
                error=str(e),
            )
            raise

    def register_model(
        self, run_id: str, model_name: str, description: Optional[str] = None
    ) -> str:
        """Register model in MLflow registry.

        Args:
            run_id: MLflow run ID
            model_name: Name for the registered model
            description: Model description

        Returns:
            Model version
        """
        try:
            model_uri = f"runs:/{run_id}/model"
            result = mlflow.register_model(model_uri, model_name)

            # Add description if provided
            if description:
                self.client.update_model_version(
                    name=model_name, version=result.version, description=description
                )

            self.logger.info(
                "Model registered successfully",
                model_name=model_name,
                version=result.version,
                run_id=run_id,
            )

            return result.version

        except Exception as e:
            self.logger.error(
                "Failed to register model",
                model_name=model_name,
                run_id=run_id,
                error=str(e),
            )
            raise
