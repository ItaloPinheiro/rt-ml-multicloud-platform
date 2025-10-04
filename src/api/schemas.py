"""Pydantic schemas for API request/response models."""

from datetime import datetime
from typing import Dict, Any, List, Optional, Union
from pydantic import BaseModel, Field, field_validator, field_serializer
import json


class PredictionRequest(BaseModel):
    """Schema for single prediction requests."""

    features: Dict[str, Any] = Field(
        ...,
        description="Feature dictionary for prediction",
        json_schema_extra={
            "example": {
                "amount": 250.00,
                "merchant_category": "electronics",
                "hour_of_day": 14,
                "is_weekend": False,
                "risk_score": 0.3
            }
        }
    )

    model_name: str = Field(
        default="fraud_detector",
        description="Name of the model to use for prediction",
        json_schema_extra={"example": "fraud_detector"}
    )

    version: Optional[str] = Field(
        default="latest",
        description="Model version (latest, specific version, or stage)",
        json_schema_extra={"example": "latest"}
    )

    return_probabilities: bool = Field(
        default=True,
        description="Whether to return prediction probabilities"
    )

    @field_validator('features')
    @classmethod
    def validate_features(cls, v):
        """Validate that features is a non-empty dictionary."""
        if not isinstance(v, dict) or len(v) == 0:
            raise ValueError("Features must be a non-empty dictionary")
        return v


class PredictionResponse(BaseModel):
    """Schema for prediction responses."""

    prediction: Union[float, int, str] = Field(
        ...,
        description="Model prediction result"
    )

    probabilities: Optional[List[float]] = Field(
        None,
        description="Prediction probabilities (for classification)"
    )

    model_name: str = Field(
        ...,
        description="Name of the model used"
    )

    model_version: str = Field(
        ...,
        description="Version of the model used"
    )

    timestamp: datetime = Field(
        ...,
        description="Timestamp of the prediction"
    )

    latency_ms: float = Field(
        ...,
        description="Prediction latency in milliseconds"
    )

    features_used: Optional[Dict[str, Any]] = Field(
        None,
        description="Features actually used for prediction (after preprocessing)"
    )

    @field_serializer('timestamp')
    def serialize_timestamp(self, timestamp: datetime, _info):
        return timestamp.isoformat()


class BatchPredictionRequest(BaseModel):
    """Schema for batch prediction requests."""

    instances: List[Dict[str, Any]] = Field(
        ...,
        description="List of feature dictionaries for batch prediction",
        min_length=1,
        max_length=1000
    )

    model_name: str = Field(
        default="fraud_detector",
        description="Name of the model to use for prediction"
    )

    version: Optional[str] = Field(
        default="latest",
        description="Model version"
    )

    return_probabilities: bool = Field(
        default=True,
        description="Whether to return prediction probabilities"
    )

    @field_validator('instances')
    @classmethod
    def validate_instances(cls, v):
        """Validate instances list."""
        if not v:
            raise ValueError("Instances list cannot be empty")

        if len(v) > 1000:
            raise ValueError("Batch size cannot exceed 1000 instances")

        return v


class BatchPredictionResponse(BaseModel):
    """Schema for batch prediction responses."""

    predictions: List[Union[float, int, str]] = Field(
        ...,
        description="List of predictions"
    )

    probabilities: Optional[List[List[float]]] = Field(
        None,
        description="List of prediction probabilities"
    )

    model_name: str = Field(
        ...,
        description="Name of the model used"
    )

    model_version: str = Field(
        ...,
        description="Version of the model used"
    )

    timestamp: datetime = Field(
        ...,
        description="Timestamp of the batch prediction"
    )

    batch_size: int = Field(
        ...,
        description="Number of instances in the batch"
    )

    total_latency_ms: float = Field(
        ...,
        description="Total batch processing latency in milliseconds"
    )

    avg_latency_ms: float = Field(
        ...,
        description="Average latency per instance in milliseconds"
    )

    @field_serializer('timestamp')
    def serialize_timestamp(self, timestamp: datetime, _info):
        return timestamp.isoformat()


class ModelInfo(BaseModel):
    """Schema for model information."""

    name: str = Field(..., description="Model name")
    versions: List[str] = Field(..., description="Available versions")
    current_stage: Optional[str] = Field(None, description="Current model stage")
    description: Optional[str] = Field(None, description="Model description")
    created_at: Optional[datetime] = Field(None, description="Model creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")
    metrics: Optional[Dict[str, float]] = Field(None, description="Model performance metrics")
    tags: Optional[Dict[str, str]] = Field(None, description="Model tags")


class HealthCheck(BaseModel):
    """Schema for health check responses."""

    status: str = Field(..., description="Overall health status")
    timestamp: datetime = Field(..., description="Health check timestamp")
    version: str = Field(..., description="API version")

    checks: Dict[str, str] = Field(
        ...,
        description="Individual service health checks",
        json_schema_extra={
            "example": {
                "api": "healthy",
                "mlflow": "healthy",
                "redis": "healthy",
                "database": "healthy"
            }
        }
    )

    uptime_seconds: Optional[float] = Field(
        None,
        description="API uptime in seconds"
    )

    @field_serializer('timestamp')
    def serialize_timestamp(self, timestamp: datetime, _info):
        return timestamp.isoformat()


class ErrorResponse(BaseModel):
    """Schema for error responses."""

    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Detailed error information")
    timestamp: datetime = Field(..., description="Error timestamp")
    request_id: Optional[str] = Field(None, description="Request ID for tracking")

    @field_serializer('timestamp')
    def serialize_timestamp(self, timestamp: datetime, _info):
        return timestamp.isoformat()


class MetricsResponse(BaseModel):
    """Schema for metrics responses."""

    total_predictions: int = Field(..., description="Total number of predictions made")
    predictions_per_minute: float = Field(..., description="Predictions per minute rate")
    avg_latency_ms: float = Field(..., description="Average prediction latency")
    error_rate: float = Field(..., description="Error rate percentage")
    active_models: int = Field(..., description="Number of active models")

    model_metrics: Dict[str, Dict[str, Any]] = Field(
        ...,
        description="Per-model metrics"
    )

    timestamp: datetime = Field(..., description="Metrics timestamp")

    @field_serializer('timestamp')
    def serialize_timestamp(self, timestamp: datetime, _info):
        return timestamp.isoformat()


class FeatureImportance(BaseModel):
    """Schema for feature importance data."""

    model_name: str = Field(..., description="Model name")
    model_version: str = Field(..., description="Model version")

    importance_scores: Dict[str, float] = Field(
        ...,
        description="Feature importance scores"
    )

    importance_type: str = Field(
        ...,
        description="Type of importance calculation",
        json_schema_extra={"example": "gain"}
    )

    timestamp: datetime = Field(..., description="Calculation timestamp")

    @field_serializer('timestamp')
    def serialize_timestamp(self, timestamp: datetime, _info):
        return timestamp.isoformat()


class ModelUpdateRequest(BaseModel):
    """Schema for model update requests."""

    model_name: str = Field(..., description="Model name to update")
    target_version: Optional[str] = Field(None, description="Target version to update to")
    target_stage: Optional[str] = Field(None, description="Target stage to promote to")
    force_update: bool = Field(False, description="Force update even if model is busy")


class ModelUpdateResponse(BaseModel):
    """Schema for model update responses."""

    model_name: str = Field(..., description="Updated model name")
    old_version: str = Field(..., description="Previous model version")
    new_version: str = Field(..., description="New model version")
    status: str = Field(..., description="Update status")
    timestamp: datetime = Field(..., description="Update timestamp")
    message: Optional[str] = Field(None, description="Update message")

    @field_serializer('timestamp')
    def serialize_timestamp(self, timestamp: datetime, _info):
        return timestamp.isoformat()


# Configuration schemas
class ModelConfig(BaseModel):
    """Schema for model configuration."""

    name: str = Field(..., description="Model name")
    version: str = Field(default="latest", description="Model version")
    preprocessing: Optional[Dict[str, Any]] = Field(None, description="Preprocessing configuration")
    postprocessing: Optional[Dict[str, Any]] = Field(None, description="Postprocessing configuration")
    cache_ttl: int = Field(default=300, description="Cache TTL in seconds")
    timeout_ms: int = Field(default=5000, description="Prediction timeout in milliseconds")


class APIConfig(BaseModel):
    """Schema for API configuration."""

    max_batch_size: int = Field(default=1000, description="Maximum batch size")
    default_timeout_ms: int = Field(default=5000, description="Default timeout")
    enable_caching: bool = Field(default=True, description="Enable response caching")
    enable_metrics: bool = Field(default=True, description="Enable metrics collection")
    log_level: str = Field(default="INFO", description="Logging level")
    cors_origins: List[str] = Field(default=["*"], description="CORS allowed origins")