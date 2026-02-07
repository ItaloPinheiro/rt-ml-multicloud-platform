"""Fast model loader that bypasses MLflow artifact proxy."""

import hashlib
import logging
import pickle
from pathlib import Path
from typing import Any, Optional

import boto3
import mlflow
from mlflow.tracking import MlflowClient

logger = logging.getLogger(__name__)


class FastModelLoader:
    """Load models directly from S3/MinIO, bypassing MLflow artifact proxy."""

    def __init__(
        self,
        mlflow_tracking_uri: str = "http://mlflow-server:5000",
        s3_endpoint_url: str = "http://mlflow-minio:9000",
        aws_access_key_id: str = "minioadmin",
        aws_secret_access_key: str = "minioadmin123",
        cache_dir: str = "/model_cache",
    ):
        self.mlflow_tracking_uri = mlflow_tracking_uri
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # MLflow client for metadata
        mlflow.set_tracking_uri(mlflow_tracking_uri)
        self.mlflow_client = MlflowClient(mlflow_tracking_uri)

        # S3 client for direct downloads
        self.s3_client = boto3.client(
            "s3",
            endpoint_url=s3_endpoint_url,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            config=boto3.session.Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": 2},
            ),
        )

    def get_cache_key(self, model_name: str, version: str) -> str:
        """Generate cache key for model."""
        return hashlib.md5(
            f"{model_name}:{version}".encode(), usedforsecurity=False
        ).hexdigest()

    def get_cached_model_path(self, model_name: str, version: str) -> Optional[Path]:
        """Check if model exists in cache."""
        cache_key = self.get_cache_key(model_name, version)
        model_path = self.cache_dir / cache_key / "model.pkl"
        if model_path.exists():
            return model_path
        return None

    def load_model(self, model_name: str, version: str = "latest") -> Any:
        """Load model with caching and direct S3 access."""
        import time

        start = time.time()

        # Resolve version
        if version == "latest":
            versions = self.mlflow_client.search_model_versions(f"name='{model_name}'")
            if not versions:
                raise ValueError(f"No versions found for model {model_name}")
            versions.sort(key=lambda x: int(x.version), reverse=True)
            version = versions[0].version

        logger.info(f"Loading {model_name}:{version}")

        # Check cache
        cached_path = self.get_cached_model_path(model_name, version)
        if cached_path:
            logger.info(f"Loading from cache: {cached_path}")
            with open(cached_path, "rb") as f:
                model = pickle.load(f)
            logger.info(f"Loaded from cache in {time.time()-start:.2f}s")
            return model

        # Get model metadata from MLflow
        model_version = self.mlflow_client.get_model_version(model_name, version)

        # Parse S3 location from artifact_uri or source
        # Try different artifact location patterns
        artifact_uri = model_version.source

        if artifact_uri.startswith("runs:/"):
            # Extract run_id from runs:/ URI
            run_id = artifact_uri.split("/")[1]

            # Try to find the S3 path
            # First, check if it's in the standard MLflow bucket structure
            bucket = "mlflow"

            # Try different possible paths
            possible_prefixes = [
                f"artifacts/{run_id}/model/",
                f"experiments/{run_id}/model/",
                f"fraud_detection_clean/{run_id}/artifacts/model/",
                f"fraud_detection/{run_id}/artifacts/model/",
                f"{run_id}/artifacts/model/",
            ]

            model_key = None
            for prefix in possible_prefixes:
                try:
                    response = self.s3_client.list_objects_v2(
                        Bucket=bucket, Prefix=prefix, MaxKeys=1
                    )
                    if response.get("KeyCount", 0) > 0:
                        # Found the model
                        model_key = f"{prefix}model.pkl"
                        logger.info(f"Found model at s3://{bucket}/{model_key}")
                        break
                except Exception:
                    continue

            if not model_key:
                # Fallback to MLflow download (slow but works)
                logger.warning(
                    "Could not find model in S3, falling back to MLflow download"
                )
                return self._fallback_mlflow_download(model_name, version)

            # Download directly from S3
            cache_key = self.get_cache_key(model_name, version)
            cache_path = self.cache_dir / cache_key
            cache_path.mkdir(parents=True, exist_ok=True)

            model_file = cache_path / "model.pkl"

            logger.info(f"Downloading from S3: s3://{bucket}/{model_key}")
            download_start = time.time()
            self.s3_client.download_file(bucket, model_key, str(model_file))
            logger.info(f"Downloaded in {time.time()-download_start:.2f}s")

            # Load the model
            with open(model_file, "rb") as f:
                model = pickle.load(f)

            logger.info(f"Total load time: {time.time()-start:.2f}s")
            return model

        else:
            # Unknown URI format, use MLflow
            return self._fallback_mlflow_download(model_name, version)

    def _fallback_mlflow_download(self, model_name: str, version: str) -> Any:
        """Fallback to MLflow download (slow but reliable)."""
        logger.warning("Using slow MLflow download as fallback")
        model_uri = f"models:/{model_name}/{version}"
        model = mlflow.pyfunc.load_model(model_uri)

        # Cache for next time
        cache_key = self.get_cache_key(model_name, version)
        cache_path = self.cache_dir / cache_key
        cache_path.mkdir(parents=True, exist_ok=True)

        # Save to cache (if it's a sklearn model)
        try:
            model_file = cache_path / "model.pkl"
            with open(model_file, "wb") as f:
                pickle.dump(model._model_impl, f)
            logger.info(f"Cached model to {model_file}")
        except Exception:
            pass  # Not all models can be pickled

        return model


# Test the fast loader
if __name__ == "__main__":
    import time

    loader = FastModelLoader()

    # Test loading
    start = time.time()
    model = loader.load_model("fraud_detector", "12")
    print(f"First load: {time.time()-start:.2f}s")

    # Test cached load
    start = time.time()
    model = loader.load_model("fraud_detector", "12")
    print(f"Cached load: {time.time()-start:.2f}s")
