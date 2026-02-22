"""FastAPI application for ML model serving.

This module provides a production-ready REST API for serving ML models
with comprehensive monitoring, caching, and error handling.
"""

import asyncio
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.middleware.gzip import GZipMiddleware
    from fastapi.responses import JSONResponse
    from starlette.concurrency import run_in_threadpool
except ImportError:
    raise ImportError("fastapi is required. Install with: pip install fastapi")

try:
    from prometheus_client import Counter, Gauge, Histogram, make_asgi_app
except ImportError:
    Counter = Histogram = Gauge = make_asgi_app = None

try:
    import redis
except ImportError:
    redis = None

try:
    import mlflow
    from mlflow.tracking import MlflowClient
except ImportError:
    mlflow = None
    MlflowClient = None

import hashlib
import json
from uuid import uuid4

import numpy as np
import pandas as pd
import structlog

from src.api.model_updater import ModelUpdateManager, handle_model_webhook
from src.api.schemas import (
    BatchPredictionRequest,
    BatchPredictionResponse,
    ErrorResponse,
    HealthCheck,
    ModelInfo,
    ModelUpdateRequest,
    ModelUpdateResponse,
    PredictionRequest,
    PredictionResponse,
)

# Import simple predict router
try:
    from src.api.simple_predict import router as simple_predict_router
except ImportError:
    simple_predict_router = None

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.dev.ConsoleRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Prometheus metrics (if available)
if Counter is not None:
    prediction_counter = Counter(
        "ml_predictions_total",
        "Total predictions made",
        ["model_name", "model_version", "status"],
    )
    prediction_latency = Histogram(
        "ml_prediction_duration_seconds",
        "Prediction latency in seconds",
        ["model_name", "model_version"],
    )
    batch_prediction_counter = Counter(
        "ml_batch_predictions_total",
        "Total batch predictions made",
        ["model_name", "model_version", "status"],
    )
    model_load_counter = Counter(
        "ml_model_loads_total",
        "Total model loads",
        ["model_name", "model_version", "status"],
    )
    active_models_gauge = Gauge("ml_active_models", "Number of active models loaded")
    api_requests_counter = Counter(
        "ml_api_requests_total", "Total API requests", ["endpoint", "method", "status"]
    )
    dependency_health_gauge = Gauge(
        "ml_dependency_health",
        "Health status of dependencies (1=Healthy, 0=Unhealthy)",
        ["dependency"],
    )
else:
    # Create dummy metrics if Prometheus is not available
    class DummyMetric:
        def labels(self, **kwargs):
            return self

        def inc(self, amount=1):
            pass

        def observe(self, amount):
            pass

        def set(self, value):
            pass

    prediction_counter = DummyMetric()
    prediction_latency = DummyMetric()
    batch_prediction_counter = DummyMetric()
    model_load_counter = DummyMetric()
    active_models_gauge = DummyMetric()
    api_requests_counter = DummyMetric()


class ModelManager:
    """Manage ML models with caching and lifecycle management."""

    def __init__(
        self,
        mlflow_uri: str,
        cache_host: str = "redis",
        cache_port: int = 6379,
        cache_password: str | None = None,
    ):
        """Initialize model manager.

        Args:
            mlflow_uri: MLflow tracking server URI
            cache_host: Redis cache host
            cache_port: Redis cache port
            cache_password: Redis cache password
        """
        self.mlflow_uri = mlflow_uri
        self.models: Dict[str, Any] = {}
        self.model_metadata: Dict[str, Dict[str, Any]] = {}
        self.cache = None

        # Initialize Redis cache if available
        if redis is not None:
            try:
                self.cache = redis.StrictRedis(
                    host=cache_host,
                    port=cache_port,
                    password=cache_password,
                    decode_responses=True,
                    socket_timeout=5,
                    socket_connect_timeout=5,
                )
                # Test connection
                self.cache.ping()
                logger.info("Redis cache connected", host=cache_host, port=cache_port)
            except Exception as e:
                logger.warning("Redis cache connection failed", error=str(e))
                self.cache = None

        # Initialize MLflow client
        if mlflow is not None:
            mlflow.set_tracking_uri(mlflow_uri)
            self.client = MlflowClient(mlflow_uri)
            logger.info("MLflow client initialized", uri=mlflow_uri)
        else:
            self.client = None
            logger.warning("MLflow not available")

    async def load_model(self, model_name: str, version: str = "latest") -> Any:
        """Load model from MLflow with caching.

        Args:
            model_name: Name of the model
            version: Model version or stage

        Returns:
            Loaded model object

        Raises:
            HTTPException: If model loading fails
        """
        cache_key = f"model:{model_name}:{version}"
        logger.info(f"load_model called for {model_name}:{version}")

        # Check if model is already loaded
        if cache_key in self.models:
            logger.debug(
                "Model loaded from memory cache", model=model_name, version=version
            )
            return self.models[cache_key]

        if self.client is None:
            logger.error("MLflow client not available")
            raise HTTPException(status_code=500, detail="MLflow client not available")

        try:
            start_time = time.time()
            logger.info(f"Loading model from MLflow: {model_name}:{version}")

            # Load model from MLflow
            if version in ["latest", "production", "staging"]:
                if version == "latest":
                    logger.info("Getting latest version...")
                    # Get the latest version
                    versions = self.client.search_model_versions(f"name='{model_name}'")
                    if not versions:
                        raise HTTPException(
                            status_code=404,
                            detail=f"No versions found for model {model_name}",
                        )
                    # Sort by version number and get the latest
                    versions.sort(key=lambda x: int(x.version), reverse=True)
                    model_version = versions[0].version
                    model_uri = f"models:/{model_name}/{model_version}"
                    logger.info(f"Using model version {model_version}")
                elif version.lower() in ["production", "staging"]:
                    # Handle production/staging requests with new MLflow approach
                    logger.info(f"Getting {version} model...")

                    # First try the new alias system (MLflow 2.9+)
                    try:
                        model_version_obj = self.client.get_model_version_by_alias(
                            model_name, version.lower()
                        )
                        if model_version_obj:
                            model_version = model_version_obj.version
                            model_uri = f"models:/{model_name}/{model_version}"
                            logger.info(
                                f"Using {version} model version {model_version} (via alias)"
                            )
                    except (AttributeError, Exception):
                        # Alias API not available, fall back to tags or latest
                        logger.debug(f"Alias API not available for {version}")

                        # Search for models with the deployment_status tag
                        versions = self.client.search_model_versions(
                            f"name='{model_name}'"
                        )
                        production_model = None

                        # Look for model tagged as production
                        for v in versions:
                            if v.tags.get("deployment_status") == version.lower():
                                production_model = v
                                break

                        if production_model:
                            model_version = production_model.version
                            model_uri = f"models:/{model_name}/{model_version}"
                            logger.info(
                                f"Using {version} model version {model_version} (via tag)"
                            )
                        else:
                            # No tagged model found, use latest as production
                            if versions and version.lower() == "production":
                                model_version = versions[0].version
                                model_uri = f"models:/{model_name}/{model_version}"
                                logger.info(
                                    f"Using latest version {model_version} as {version}"
                                )
                            else:
                                raise HTTPException(
                                    status_code=404,
                                    detail=f"No {version} model found for {model_name}",
                                )
                else:
                    model_uri = f"models:/{model_name}/{version}"
                    model_version = version
            else:
                model_uri = f"models:/{model_name}/{version}"
                model_version = version

            logger.info(f"Loading model from URI: {model_uri}")
            # Load the model - run synchronously in executor to avoid blocking
            loop = asyncio.get_event_loop()
            model = await loop.run_in_executor(
                None, mlflow.pyfunc.load_model, model_uri
            )
            logger.info("Model loaded successfully")

            # Cache the model
            self.models[cache_key] = model

            # Store metadata
            self.model_metadata[cache_key] = {
                "name": model_name,
                "version": model_version,
                "uri": model_uri,
                "loaded_at": datetime.now(timezone.utc).isoformat(),
                "load_time_ms": (time.time() - start_time) * 1000,
            }

            # Update metrics
            load_time = time.time() - start_time
            model_load_counter.labels(
                model_name=model_name, model_version=model_version, status="success"
            ).inc()
            active_models_gauge.set(len(self.models))

            logger.info(
                "Model loaded successfully",
                model=model_name,
                version=model_version,
                load_time_ms=load_time * 1000,
            )

            return model

        except Exception as e:
            model_load_counter.labels(
                model_name=model_name, model_version=version, status="error"
            ).inc()

            logger.error(
                "Model loading failed", model=model_name, version=version, error=str(e)
            )
            raise HTTPException(
                status_code=500, detail=f"Failed to load model: {str(e)}"
            )

    async def predict(
        self,
        model_name: str,
        features: Dict[str, Any],
        version: str = "latest",
        return_probabilities: bool = True,
    ) -> Dict[str, Any]:
        """Make prediction with caching.

        Args:
            model_name: Name of the model
            features: Input features
            version: Model version
            return_probabilities: Whether to return probabilities

        Returns:
            Prediction result dictionary
        """
        start_time = time.time()

        try:
            # Generate cache key for prediction
            features_hash = hashlib.md5(
                json.dumps(features, sort_keys=True).encode(), usedforsecurity=False
            ).hexdigest()
            cache_key = f"pred:{model_name}:{version}:{features_hash}"

            # Check cache first
            cached_result = None
            if self.cache:
                try:
                    cached_result = self.cache.get(cache_key)
                    if cached_result:
                        cached_result = json.loads(cached_result)
                        logger.debug(
                            "Prediction served from cache", cache_key=cache_key
                        )
                except Exception as e:
                    logger.warning("Cache read failed", error=str(e))

            if cached_result:
                prediction_counter.labels(
                    model_name=model_name, model_version=version, status="cache_hit"
                ).inc()
                return cached_result

            # Load model
            model = await self.load_model(model_name, version)

            # Prepare features
            features_df = pd.DataFrame([features])

            # Make prediction
            prediction = model.predict(features_df)

            # Get probabilities if requested and available
            probabilities = None
            if return_probabilities:
                try:
                    if hasattr(model, "predict_proba"):
                        probabilities = model.predict_proba(features_df)[0].tolist()
                    else:
                        # Try to get probabilities from the underlying model
                        underlying_model = getattr(model, "_model_impl", None)
                        if underlying_model and hasattr(
                            underlying_model, "predict_proba"
                        ):
                            probabilities = underlying_model.predict_proba(features_df)[
                                0
                            ].tolist()
                except Exception as e:
                    logger.warning("Failed to get probabilities", error=str(e))

            # Calculate latency
            latency_ms = (time.time() - start_time) * 1000

            # Get model metadata
            cache_key_model = f"model:{model_name}:{version}"
            metadata = self.model_metadata.get(cache_key_model, {})
            actual_version = metadata.get("version", version)

            # Prepare result
            result = {
                "prediction": (
                    float(prediction[0])
                    if isinstance(prediction[0], (np.integer, np.floating))
                    else prediction[0]
                ),
                "probabilities": probabilities,
                "model_name": model_name,
                "model_version": actual_version,
                "latency_ms": latency_ms,
                "timestamp": datetime.now(timezone.utc),
                "features_used": features,
            }

            # Cache result
            if self.cache and latency_ms < 1000:  # Only cache fast predictions
                try:
                    self.cache.setex(
                        cache_key, 300, json.dumps(result, default=str)  # 5 minutes TTL
                    )
                except Exception as e:
                    logger.warning("Cache write failed", error=str(e))

            # Update metrics
            prediction_counter.labels(
                model_name=model_name, model_version=actual_version, status="success"
            ).inc()

            prediction_latency.labels(
                model_name=model_name, model_version=actual_version
            ).observe(latency_ms / 1000)

            return result

        except HTTPException:
            raise
        except Exception as e:
            prediction_counter.labels(
                model_name=model_name, model_version=version, status="error"
            ).inc()

            logger.error(
                "Prediction failed", model=model_name, version=version, error=str(e)
            )
            raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}")

    async def predict_batch(
        self,
        model_name: str,
        instances: List[Dict[str, Any]],
        version: str = "latest",
        return_probabilities: bool = True,
    ) -> Dict[str, Any]:
        """Make batch predictions.

        Args:
            model_name: Name of the model
            instances: List of feature dictionaries
            version: Model version
            return_probabilities: Whether to return probabilities

        Returns:
            Batch prediction result dictionary
        """
        start_time = time.time()

        try:
            # Load model
            model = await self.load_model(model_name, version)

            # Prepare features
            features_df = pd.DataFrame(instances)

            # Make predictions
            predictions = model.predict(features_df)

            # Get probabilities if requested
            probabilities = None
            if return_probabilities:
                try:
                    if hasattr(model, "predict_proba"):
                        probabilities = model.predict_proba(features_df).tolist()
                    else:
                        underlying_model = getattr(model, "_model_impl", None)
                        if underlying_model and hasattr(
                            underlying_model, "predict_proba"
                        ):
                            probabilities = underlying_model.predict_proba(
                                features_df
                            ).tolist()
                except Exception as e:
                    logger.warning("Failed to get batch probabilities", error=str(e))

            # Calculate metrics
            total_latency_ms = (time.time() - start_time) * 1000
            avg_latency_ms = total_latency_ms / len(instances)

            # Get model metadata
            cache_key_model = f"model:{model_name}:{version}"
            metadata = self.model_metadata.get(cache_key_model, {})
            actual_version = metadata.get("version", version)

            # Prepare result
            result = {
                "predictions": [
                    float(pred) if isinstance(pred, (np.integer, np.floating)) else pred
                    for pred in predictions
                ],
                "probabilities": probabilities,
                "model_name": model_name,
                "model_version": actual_version,
                "batch_size": len(instances),
                "total_latency_ms": total_latency_ms,
                "avg_latency_ms": avg_latency_ms,
                "timestamp": datetime.now(timezone.utc),
            }

            # Update metrics
            batch_prediction_counter.labels(
                model_name=model_name, model_version=actual_version, status="success"
            ).inc()

            return result

        except HTTPException:
            raise
        except Exception as e:
            batch_prediction_counter.labels(
                model_name=model_name, model_version=version, status="error"
            ).inc()

            logger.error(
                "Batch prediction failed",
                model=model_name,
                version=version,
                batch_size=len(instances),
                error=str(e),
            )
            raise HTTPException(
                status_code=500, detail=f"Batch prediction failed: {str(e)}"
            )

    def get_model_info(self) -> List[Dict[str, Any]]:
        """Get information about loaded models."""
        models_info = []
        seen_models = {}  # Track unique models by name

        for cache_key, metadata in self.model_metadata.items():
            model_name = metadata.get("name")

            # Only add if we haven't seen this model, or if this version is newer
            if model_name not in seen_models:
                seen_models[model_name] = metadata
                models_info.append({"cache_key": cache_key, **metadata})
            else:
                # Keep the most recent load (higher loaded_at timestamp)
                existing = seen_models[model_name]
                if metadata.get("loaded_at", "") > existing.get("loaded_at", ""):
                    # Remove the old entry and add the new one
                    models_info = [
                        m for m in models_info if m.get("name") != model_name
                    ]
                    seen_models[model_name] = metadata
                    models_info.append({"cache_key": cache_key, **metadata})

        return models_info

    def clear_cache(self, model_name: Optional[str] = None) -> int:
        """Clear model cache.

        Args:
            model_name: Specific model to clear, or None for all

        Returns:
            Number of models removed from cache
        """
        if model_name:
            # Clear specific model
            keys_to_remove = [
                k for k in self.models.keys() if k.startswith(f"model:{model_name}:")
            ]
        else:
            # Clear all models
            keys_to_remove = list(self.models.keys())

        for key in keys_to_remove:
            self.models.pop(key, None)
            self.model_metadata.pop(key, None)

        active_models_gauge.set(len(self.models))

        logger.info(
            "Model cache cleared", removed_count=len(keys_to_remove), model=model_name
        )
        return len(keys_to_remove)


# Global model manager and update manager
model_manager = None
update_manager = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global model_manager, update_manager

    # Startup
    logger.info("Starting ML Model API")

    # Initialize model manager
    mlflow_uri = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    redis_password = os.getenv("REDIS_PASSWORD")

    model_manager = ModelManager(mlflow_uri, redis_host, redis_port, redis_password)

    # Preload default models
    try:
        default_models = os.getenv("PRELOAD_MODELS", "").split(",")
        for model_spec in default_models:
            if model_spec.strip():
                if ":" in model_spec:
                    model_name, version = model_spec.split(":", 1)
                else:
                    model_name, version = model_spec, "latest"

                try:
                    await model_manager.load_model(model_name.strip(), version.strip())
                    logger.info("Preloaded model", model=model_name, version=version)
                except Exception as e:
                    logger.warning(
                        "Failed to preload model", model=model_name, error=str(e)
                    )
    except Exception as e:
        logger.warning("Failed to preload models", error=str(e))

    # Initialize model update manager if auto-update is enabled
    update_task = None
    if os.getenv("MODEL_AUTO_UPDATE", "true").lower() == "true":
        try:
            check_interval = int(os.getenv("MODEL_UPDATE_INTERVAL", "60"))
            update_manager = ModelUpdateManager(
                model_manager=model_manager,
                mlflow_uri=mlflow_uri,
                check_interval=check_interval,
            )

            # Start background update task
            update_task = asyncio.create_task(update_manager.run_update_loop())
            logger.info("Model auto-update enabled", check_interval=check_interval)
        except Exception as e:
            logger.warning("Failed to start model update manager", error=str(e))

    # Initialize dependency health task
    health_task = None
    if dependency_health_gauge is not None:
        health_task = asyncio.create_task(update_dependency_health())
        logger.info("Dependency health monitoring enabled")

    logger.info("ML Model API startup completed")

    yield

    # Shutdown
    if update_task:
        update_task.cancel()
    if health_task:
        health_task.cancel()
        try:
            await update_task
        except asyncio.CancelledError:
            pass

    logger.info("Shutting down ML Model API")


# Create FastAPI application
app = FastAPI(
    title="ML Model Serving API",
    description="Production-ready ML model serving with real-time predictions",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

# Include simple predict router if available
if simple_predict_router:
    app.include_router(simple_predict_router)

# Mount Prometheus metrics if available
if make_asgi_app is not None:
    metrics_app = make_asgi_app(disable_compression=True)
    app.mount("/metrics", metrics_app)


# Middleware for request tracking
@app.middleware("http")
async def track_requests(request: Request, call_next):
    """Track API requests with metrics and logging."""
    start_time = time.time()
    request_id = str(uuid4())

    # Add request ID to context
    with structlog.contextvars.bound_contextvars(request_id=request_id):
        response = await call_next(request)

        # Calculate latency
        latency = time.time() - start_time

        # Update metrics
        api_requests_counter.labels(
            endpoint=request.url.path,
            method=request.method,
            status=response.status_code,
        ).inc()

        # Log request
        logger.info(
            "API request completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            latency_ms=latency * 1000,
            request_id=request_id,
        )

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id

        return response


if dependency_health_gauge is not None:

    async def update_dependency_health():
        """Background task to update dependency health metrics."""
        while True:
            try:
                # Check MLflow
                mlflow_status = 0
                if model_manager and model_manager.client:
                    try:
                        # Use a light operation to check connectivity
                        await asyncio.wait_for(
                            run_in_threadpool(model_manager.client.search_experiments, max_results=1),
                            timeout=2.0
                        )
                        mlflow_status = 1
                    except Exception:
                        pass
                dependency_health_gauge.labels(dependency="mlflow").set(mlflow_status)

                # Check Redis
                redis_status = 0
                if model_manager and model_manager.cache:
                    try:
                        await asyncio.wait_for(
                            run_in_threadpool(model_manager.cache.ping),
                            timeout=2.0
                        )
                        redis_status = 1
                    except Exception:
                        pass
                dependency_health_gauge.labels(dependency="redis").set(redis_status)

            except Exception as e:
                if logger:
                    logger.error(
                        "Failed to update dependency health metrics", error=str(e)
                    )

            await asyncio.sleep(5)


# Health check endpoints
@app.get("/", response_model=HealthCheck)
@app.get("/health", response_model=HealthCheck)
async def health_check():
    """API health check."""
    checks = {"api": "healthy"}

    # Check MLflow connection
    if model_manager and model_manager.client:
        try:
            await asyncio.wait_for(
                run_in_threadpool(model_manager.client.search_experiments, max_results=1),
                timeout=2.0
            )
            checks["mlflow"] = "healthy"
        except Exception:
            checks["mlflow"] = "unhealthy"
    else:
        checks["mlflow"] = "unavailable"

    # Check Redis connection
    if model_manager and model_manager.cache:
        try:
            await asyncio.wait_for(
                run_in_threadpool(model_manager.cache.ping),
                timeout=2.0
            )
            checks["redis"] = "healthy"
        except Exception:
            checks["redis"] = "unhealthy"
    else:
        checks["redis"] = "unavailable"

    overall_status = (
        "healthy"
        if all(v in ["healthy", "unavailable"] for v in checks.values())
        else "degraded"
    )

    return HealthCheck(
        status=overall_status,
        timestamp=datetime.now(timezone.utc),
        version="1.0.0",
        checks=checks,
    )


# Prediction endpoints
@app.post("/predict", response_model=PredictionResponse)
async def predict(request: PredictionRequest, background_tasks: BackgroundTasks):
    """Make a single prediction."""
    if not model_manager:
        raise HTTPException(status_code=500, detail="Model manager not initialized")

    try:
        result = await model_manager.predict(
            model_name=request.model_name,
            features=request.features,
            version=request.version,
            return_probabilities=request.return_probabilities,
        )

        # Log prediction in background
        background_tasks.add_task(
            log_prediction, request.model_name, request.features, result["prediction"]
        )

        return PredictionResponse(**result)
    except Exception as e:
        logger.error("Prediction failed", error=str(e), model_name=request.model_name)
        raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}")


@app.post("/predict/batch", response_model=BatchPredictionResponse)
async def predict_batch(request: BatchPredictionRequest):
    """Make batch predictions."""
    if not model_manager:
        raise HTTPException(status_code=500, detail="Model manager not initialized")

    result = await model_manager.predict_batch(
        model_name=request.model_name,
        instances=request.instances,
        version=request.version,
        return_probabilities=request.return_probabilities,
    )

    return BatchPredictionResponse(**result)


# Model management endpoints
@app.get("/models", response_model=List[ModelInfo])
async def list_models():
    """List available models."""
    if not model_manager:
        raise HTTPException(status_code=500, detail="Model manager not initialized")

    models_info = model_manager.get_model_info()
    return [
        ModelInfo(
            name=info["name"],
            versions=[info["version"]],
            current_stage="loaded",
            created_at=datetime.fromisoformat(info["loaded_at"]),
            description=f"Loaded model with {info['load_time_ms']:.1f}ms load time",
        )
        for info in models_info
    ]


@app.post("/models/reload")
async def reload_model(request: ModelUpdateRequest):
    """Reload or update a model."""
    if not model_manager:
        raise HTTPException(status_code=500, detail="Model manager not initialized")

    # Clear existing model from cache
    cleared_count = model_manager.clear_cache(request.model_name)

    # Load new version
    try:
        target_version = request.target_version or "latest"
        await model_manager.load_model(request.model_name, target_version)

        return ModelUpdateResponse(
            model_name=request.model_name,
            old_version="cleared",
            new_version=target_version,
            status="success",
            timestamp=datetime.now(timezone.utc),
            message=f"Model reloaded successfully. Cleared {cleared_count} cached versions.",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reload model: {str(e)}")


@app.delete("/models/{model_name}/cache")
async def clear_model_cache(model_name: str):
    """Clear cache for a specific model."""
    if not model_manager:
        raise HTTPException(status_code=500, detail="Model manager not initialized")

    cleared_count = model_manager.clear_cache(model_name)
    return {
        "message": f"Cleared {cleared_count} cached versions for model {model_name}"
    }


# Model update endpoints
@app.get("/models/updates/status")
async def get_update_status():
    """Get status of the model update manager."""
    if not update_manager:
        return {"enabled": False, "message": "Model auto-update is disabled"}

    return {"enabled": True, **update_manager.get_status()}


@app.post("/models/updates/check")
async def check_for_updates():
    """Manually trigger a check for model updates."""
    if not update_manager:
        raise HTTPException(status_code=400, detail="Model auto-update is disabled")

    updates = await update_manager.check_for_updates()

    if updates:
        # Load the updates
        results = {}
        for model_name, version in updates.items():
            success = await update_manager.load_new_model(model_name, version)
            results[model_name] = {
                "version": version,
                "status": "loaded" if success else "failed",
            }

        return {"updates_found": len(updates), "results": results}

    return {"updates_found": 0, "message": "All models are up to date"}


@app.post("/webhooks/mlflow/model-update")
async def mlflow_model_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle MLflow webhook for model updates.

    This endpoint should be configured in MLflow or called by CI/CD pipeline
    when a new model is registered or promoted to production.
    """
    if not update_manager:
        return {"status": "disabled", "message": "Model auto-update is disabled"}

    try:
        payload = await request.json()

        # Extract model information from webhook
        model_name = payload.get("model_name")
        version = payload.get("version")
        action = payload.get("action", "registered")

        if not model_name or not version:
            raise HTTPException(status_code=400, detail="Missing model_name or version")

        # Handle the webhook in background
        background_tasks.add_task(
            handle_model_webhook, model_name, version, action, update_manager
        )

        return {
            "status": "accepted",
            "model": model_name,
            "version": version,
            "message": "Update will be processed in background",
        }

    except Exception as e:
        logger.error("Failed to process webhook", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))


# Utility functions
async def log_prediction(model_name: str, features: Dict[str, Any], prediction: Any):
    """Log prediction for monitoring and analytics."""
    try:
        if model_manager and model_manager.cache:
            # Redis xadd requires all field values to be scalars (str/bytes/int/float).
            # Serialize features dict and coerce prediction (may be numpy type) to str.
            def _xadd():
                model_manager.cache.xadd(
                    f"predictions:{model_name}",
                    {
                        "model_name": model_name,
                        "features": json.dumps(features),
                        "prediction": str(prediction),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                    maxlen=10000,  # Keep last 10k predictions
                )

            await run_in_threadpool(_xadd)
    except Exception as e:
        logger.error("Failed to log prediction", error=str(e))


# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error="HTTPException",
            message=exc.detail,
            timestamp=datetime.now(timezone.utc),
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions."""
    logger.error("Unhandled exception", error=str(exc), path=request.url.path)

    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="InternalServerError",
            message="An internal server error occurred",
            detail=str(exc),
            timestamp=datetime.now(timezone.utc),
        ).model_dump(),
    )
