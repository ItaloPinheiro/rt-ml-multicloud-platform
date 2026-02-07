"""Automatic model update system for the ML API.

This module provides automatic detection and loading of new model versions
with zero-downtime updates and proper health checks.
"""

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import mlflow
import structlog
from mlflow.tracking import MlflowClient

# Configure structured logging
logger = structlog.get_logger()


class ModelUpdateManager:
    """Manages automatic model updates with zero-downtime deployment."""

    def __init__(
        self,
        model_manager,
        mlflow_uri: str = "http://mlflow-server:5000",
        check_interval: int = 60,  # Check every minute
        models_to_track: Optional[List[str]] = None,
    ):
        """Initialize the model update manager.

        Args:
            model_manager: The ModelManager instance from main.py
            mlflow_uri: MLflow tracking server URI
            check_interval: Seconds between update checks
            models_to_track: List of model names to track (None = track all from PRELOAD_MODELS)
        """
        self.model_manager = model_manager
        self.mlflow_uri = mlflow_uri
        self.check_interval = check_interval
        self.models_to_track = models_to_track or self._get_tracked_models()

        # Initialize MLflow client
        mlflow.set_tracking_uri(mlflow_uri)
        self.mlflow_client = MlflowClient(mlflow_uri)

        # Track current versions
        self.current_versions: Dict[str, str] = {}
        self.last_check: Dict[str, datetime] = {}
        self.update_history: List[Dict[str, Any]] = []

        # Metrics
        self.update_count = 0
        self.failed_updates = 0

        logger.info(
            "Model update manager initialized",
            models=self.models_to_track,
            check_interval=check_interval,
        )

    def _get_tracked_models(self) -> List[str]:
        """Get models to track from environment variable."""
        preload_models = os.getenv("PRELOAD_MODELS", "")
        if not preload_models:
            return []

        models = []
        for model_spec in preload_models.split(","):
            if model_spec.strip():
                model_name = model_spec.split(":")[0].strip()
                models.append(model_name)

        return models

    async def get_latest_model_version(self, model_name: str) -> Optional[str]:
        """Get the latest version of a model from MLflow.

        Since MLflow stages are deprecated, we now simply get the latest version
        which should be the one marked for production use.

        Args:
            model_name: Name of the model

        Returns:
            Latest version number or None if not found
        """
        try:
            # Get the latest version (which should be our production model)
            versions = self.mlflow_client.search_model_versions(
                f"name='{model_name}'", order_by=["version_number DESC"], max_results=1
            )

            if versions:
                # Check if this version has a "Production" tag or alias
                # For now, we'll use the latest version as production
                latest_version = versions[0]
                logger.debug(
                    f"Found latest model version {latest_version.version} for {model_name}"
                )

                # Optional: Check for production alias/tag if using MLflow 2.9+
                # This is forward-compatible with the new alias system
                try:
                    # Try to get model by alias if available in newer MLflow versions
                    from mlflow import MlflowClient

                    client = MlflowClient()
                    # Try the new alias-based API (MLflow 2.9+)
                    model_version = client.get_model_version_by_alias(
                        model_name, "production"
                    )
                    if model_version:
                        logger.debug(
                            f"Found model with 'production' alias: version {model_version.version}"
                        )
                        return model_version.version
                except (AttributeError, Exception):
                    # Method doesn't exist or failed, use latest version
                    pass

                return latest_version.version

            return None
        except Exception as e:
            logger.error(
                "Failed to get latest model version",
                model_name=model_name,
                error=str(e),
            )
            return None

    async def check_for_updates(self) -> Dict[str, str]:
        """Check for new model versions.

        Returns:
            Dictionary of models with new versions {model_name: new_version}
        """
        updates = {}

        for model_name in self.models_to_track:
            try:
                # Get latest version from MLflow
                latest_version = await self.get_latest_model_version(model_name)

                if latest_version:
                    current_version = self.current_versions.get(model_name)

                    # Check if it's a new version
                    if current_version != latest_version:
                        updates[model_name] = latest_version
                        logger.info(
                            "New model version detected",
                            model=model_name,
                            current=current_version,
                            latest=latest_version,
                        )

                self.last_check[model_name] = datetime.now(timezone.utc)

            except Exception as e:
                logger.error(
                    "Error checking model updates", model=model_name, error=str(e)
                )

        return updates

    async def load_new_model(
        self, model_name: str, version: str, validate: bool = True
    ) -> bool:
        """Load a new model version with validation.

        Args:
            model_name: Name of the model
            version: Version to load
            validate: Whether to validate the model before switching

        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info("Loading new model version", model=model_name, version=version)

            start_time = time.time()

            # Load the new model (this will cache it)
            await self.model_manager.load_model(model_name, version)

            load_time = time.time() - start_time

            if validate:
                # Validate the model with a test prediction
                if not await self._validate_model(model_name, version):
                    logger.error(
                        "Model validation failed", model=model_name, version=version
                    )
                    # Remove from cache
                    cache_key = f"model:{model_name}:{version}"
                    self.model_manager.models.pop(cache_key, None)
                    return False

            # Update current version tracking
            old_version = self.current_versions.get(model_name)
            self.current_versions[model_name] = version

            # Record update in history
            self.update_history.append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "model_name": model_name,
                    "old_version": old_version,
                    "new_version": version,
                    "load_time_seconds": load_time,
                    "status": "success",
                }
            )

            self.update_count += 1

            logger.info(
                "Model updated successfully",
                model=model_name,
                version=version,
                load_time=f"{load_time:.2f}s",
            )

            # Update the "latest" alias to point to new version
            latest_key = f"model:{model_name}:latest"
            new_key = f"model:{model_name}:{version}"
            if new_key in self.model_manager.models:
                self.model_manager.models[latest_key] = self.model_manager.models[
                    new_key
                ]
                self.model_manager.model_metadata[latest_key] = (
                    self.model_manager.model_metadata[new_key].copy()
                )

            return True

        except Exception as e:
            logger.error(
                "Failed to load new model",
                model=model_name,
                version=version,
                error=str(e),
            )

            self.failed_updates += 1

            self.update_history.append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "model_name": model_name,
                    "old_version": self.current_versions.get(model_name),
                    "new_version": version,
                    "status": "failed",
                    "error": str(e),
                }
            )

            return False

    async def _validate_model(self, model_name: str, version: str) -> bool:
        """Validate a model with a test prediction.

        Args:
            model_name: Name of the model
            version: Version to validate

        Returns:
            True if validation passes
        """
        try:
            # Create test data (use floats for nullable-safe schema compatibility)
            test_features = {
                "hour_of_day": 12.0,
                "day_of_week": 1.0,
                "is_weekend": False,
                "transaction_count_24h": 5.0,
                "avg_amount_30d": 100.0,
                "risk_score": 0.5,
                "amount": 50.0,
                "merchant_category_encoded": 1.0,
                "payment_method_encoded": 1.0,
            }

            # Try a prediction
            result = await self.model_manager.predict(
                model_name=model_name,
                features=test_features,
                version=version,
                return_probabilities=False,
            )

            # Check if we got a valid result
            if "prediction" in result:
                logger.debug(
                    "Model validation passed",
                    model=model_name,
                    version=version,
                    test_prediction=result["prediction"],
                )
                return True

            return False

        except Exception as e:
            logger.error(
                "Model validation error",
                model=model_name,
                version=version,
                error=str(e),
            )
            return False

    async def run_update_loop(self):
        """Main update loop that runs continuously."""
        logger.info("Starting model update loop")

        # Initialize current versions
        for model_name in self.models_to_track:
            try:
                # Get currently loaded version
                for key in self.model_manager.models.keys():
                    if key.startswith(f"model:{model_name}:"):
                        version = key.split(":")[-1]
                        if version != "latest":
                            self.current_versions[model_name] = version
                            break
            except Exception:
                pass

        while True:
            try:
                # Check for updates
                updates = await self.check_for_updates()

                if updates:
                    logger.info(
                        "Found model updates",
                        count=len(updates),
                        models=list(updates.keys()),
                    )

                    # Load new models
                    for model_name, new_version in updates.items():
                        success = await self.load_new_model(
                            model_name, new_version, validate=True
                        )

                        if success:
                            # Optionally clear old versions after successful update
                            await self._cleanup_old_versions(model_name, new_version)

                # Wait before next check
                await asyncio.sleep(self.check_interval)

            except Exception as e:
                logger.error("Error in update loop", error=str(e))
                await asyncio.sleep(self.check_interval)

    async def _cleanup_old_versions(
        self, model_name: str, keep_version: str, keep_count: int = 2
    ):
        """Clean up old model versions from cache.

        Args:
            model_name: Name of the model
            keep_version: Version to keep
            keep_count: Number of recent versions to keep
        """
        try:
            # Find all cached versions
            cached_versions = []
            for key in list(self.model_manager.models.keys()):
                if key.startswith(f"model:{model_name}:"):
                    version = key.split(":")[-1]
                    if version not in ["latest", keep_version]:
                        cached_versions.append((version, key))

            # Sort by version number
            cached_versions.sort(
                key=lambda x: int(x[0]) if x[0].isdigit() else 0, reverse=True
            )

            # Remove old versions keeping only recent ones
            for version, key in cached_versions[keep_count - 1 :]:
                logger.info(
                    "Removing old model version from cache",
                    model=model_name,
                    version=version,
                )
                self.model_manager.models.pop(key, None)
                self.model_manager.model_metadata.pop(key, None)

        except Exception as e:
            logger.error(
                "Error cleaning up old versions", model=model_name, error=str(e)
            )

    def get_status(self) -> Dict[str, Any]:
        """Get current status of the update manager.

        Returns:
            Status dictionary
        """
        return {
            "tracking_models": self.models_to_track,
            "current_versions": self.current_versions,
            "last_check": {
                model: check.isoformat() if check else None
                for model, check in self.last_check.items()
            },
            "update_count": self.update_count,
            "failed_updates": self.failed_updates,
            "check_interval_seconds": self.check_interval,
            "recent_updates": self.update_history[-10:],  # Last 10 updates
        }


async def handle_model_webhook(
    model_name: str, version: str, action: str, update_manager: ModelUpdateManager
) -> Dict[str, Any]:
    """Handle webhook notification for model updates.

    Args:
        model_name: Name of the model
        version: New version
        action: Action type (e.g., "registered", "transitioned_to_production")
        update_manager: The update manager instance

    Returns:
        Response dictionary
    """
    logger.info(
        "Received model webhook", model=model_name, version=version, action=action
    )

    # Only process if it's a tracked model
    if model_name not in update_manager.models_to_track:
        return {"status": "ignored", "reason": "Model not tracked", "model": model_name}

    # Trigger immediate update check
    if action in ["registered", "transitioned_to_production"]:
        success = await update_manager.load_new_model(
            model_name, version, validate=True
        )

        return {
            "status": "processed" if success else "failed",
            "model": model_name,
            "version": version,
            "action": action,
        }

    return {
        "status": "ignored",
        "reason": f"Action {action} not handled",
        "model": model_name,
    }
