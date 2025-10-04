"""SQLAlchemy models for ML pipeline data persistence."""

from datetime import datetime, timezone
from typing import Dict, Any, Optional
from sqlalchemy import (
    Column, Integer, String, DateTime, Float, Text, Boolean,
    JSON, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship, validates
from sqlalchemy.dialects.postgresql import UUID
import uuid

Base = declarative_base()


class Experiment(Base):
    """Model for tracking ML experiments."""

    __tablename__ = "experiments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    is_active = Column(Boolean, default=True, nullable=False)

    # Metadata
    tags = Column(JSON, default=dict)
    artifact_location = Column(String(512))

    # Relationships
    model_runs = relationship("ModelRun", back_populates="experiment", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index('idx_experiments_name', 'name'),
        Index('idx_experiments_created_at', 'created_at'),
        Index('idx_experiments_is_active', 'is_active'),
    )

    def __repr__(self):
        return f"<Experiment(id={self.id}, name='{self.name}')>"


class ModelRun(Base):
    """Model for tracking individual model training runs."""

    __tablename__ = "model_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    experiment_id = Column(UUID(as_uuid=True), ForeignKey("experiments.id"), nullable=False)

    # Run metadata
    run_name = Column(String(255))
    model_name = Column(String(255), nullable=False)
    model_version = Column(String(100))
    status = Column(String(50), default="RUNNING", nullable=False)  # RUNNING, FINISHED, FAILED, KILLED

    # Timing
    start_time = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    end_time = Column(DateTime)
    duration_seconds = Column(Float)

    # Model artifacts
    artifact_uri = Column(String(512))
    model_uri = Column(String(512))
    source_name = Column(String(255))
    source_version = Column(String(100))

    # Parameters and metrics
    parameters = Column(JSON, default=dict)
    metrics = Column(JSON, default=dict)
    tags = Column(JSON, default=dict)

    # Model metadata
    model_type = Column(String(100))  # classification, regression, clustering, etc.
    framework = Column(String(100))   # sklearn, xgboost, pytorch, etc.

    # Feature information
    feature_names = Column(JSON, default=list)
    feature_importance = Column(JSON, default=dict)

    # Performance tracking
    training_data_size = Column(Integer)
    validation_score = Column(Float)
    test_score = Column(Float)

    # Relationships
    experiment = relationship("Experiment", back_populates="model_runs")
    prediction_logs = relationship("PredictionLog", back_populates="model_run")

    # Indexes
    __table_args__ = (
        Index('idx_model_runs_experiment_id', 'experiment_id'),
        Index('idx_model_runs_model_name', 'model_name'),
        Index('idx_model_runs_status', 'status'),
        Index('idx_model_runs_start_time', 'start_time'),
        Index('idx_model_runs_model_name_version', 'model_name', 'model_version'),
    )

    @validates('status')
    def validate_status(self, key, status):
        """Validate status values."""
        valid_statuses = ['RUNNING', 'FINISHED', 'FAILED', 'KILLED']
        if status not in valid_statuses:
            raise ValueError(f"Status must be one of {valid_statuses}")
        return status

    def __repr__(self):
        return f"<ModelRun(id={self.id}, model_name='{self.model_name}', status='{self.status}')>"


class FeatureStore(Base):
    """Model for feature store data persistence."""

    __tablename__ = "feature_store"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Feature identification
    entity_id = Column(String(255), nullable=False)
    feature_group = Column(String(255), nullable=False)
    feature_name = Column(String(255), nullable=False)

    # Feature data
    feature_value = Column(JSON, nullable=False)
    data_type = Column(String(50), nullable=False)  # numeric, categorical, text, datetime

    # Timing and versioning
    event_timestamp = Column(DateTime, nullable=False)
    ingestion_timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    feature_version = Column(String(100), default="1.0")

    # Metadata
    source_system = Column(String(255))
    tags = Column(JSON, default=dict)

    # TTL and lifecycle
    ttl_timestamp = Column(DateTime)
    is_active = Column(Boolean, default=True, nullable=False)

    # Indexes
    __table_args__ = (
        Index('idx_feature_store_entity_id', 'entity_id'),
        Index('idx_feature_store_feature_group', 'feature_group'),
        Index('idx_feature_store_feature_name', 'feature_name'),
        Index('idx_feature_store_event_timestamp', 'event_timestamp'),
        Index('idx_feature_store_ingestion_timestamp', 'ingestion_timestamp'),
        Index('idx_feature_store_ttl_timestamp', 'ttl_timestamp'),
        Index('idx_feature_store_entity_feature', 'entity_id', 'feature_group', 'feature_name'),
        UniqueConstraint('entity_id', 'feature_group', 'feature_name', 'event_timestamp',
                        name='uq_feature_store_entity_feature_time'),
    )

    @validates('data_type')
    def validate_data_type(self, key, data_type):
        """Validate data type values."""
        valid_types = ['numeric', 'categorical', 'text', 'datetime', 'boolean']
        if data_type not in valid_types:
            raise ValueError(f"Data type must be one of {valid_types}")
        return data_type

    def __repr__(self):
        return f"<FeatureStore(entity_id='{self.entity_id}', feature_group='{self.feature_group}', feature_name='{self.feature_name}')>"


class PredictionLog(Base):
    """Model for logging prediction requests and responses."""

    __tablename__ = "prediction_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_run_id = Column(UUID(as_uuid=True), ForeignKey("model_runs.id"))

    # Request metadata
    request_id = Column(String(255))
    model_name = Column(String(255), nullable=False)
    model_version = Column(String(100), nullable=False)

    # Timing
    request_timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    response_timestamp = Column(DateTime)
    latency_ms = Column(Float)

    # Request/Response data
    input_features = Column(JSON, nullable=False)
    prediction = Column(JSON, nullable=False)
    probabilities = Column(JSON)

    # Request context
    user_id = Column(String(255))
    session_id = Column(String(255))
    client_ip = Column(String(45))  # IPv6 compatible
    user_agent = Column(String(512))

    # Response metadata
    status_code = Column(Integer, default=200)
    error_message = Column(Text)

    # Feature importance for this prediction
    feature_importance = Column(JSON)

    # Feedback and monitoring
    feedback_score = Column(Float)  # User feedback on prediction quality
    actual_outcome = Column(JSON)   # Actual outcome for model monitoring
    is_flagged = Column(Boolean, default=False)  # Flagged for review

    # Relationships
    model_run = relationship("ModelRun", back_populates="prediction_logs")

    # Indexes
    __table_args__ = (
        Index('idx_prediction_logs_model_name', 'model_name'),
        Index('idx_prediction_logs_model_version', 'model_version'),
        Index('idx_prediction_logs_request_timestamp', 'request_timestamp'),
        Index('idx_prediction_logs_latency_ms', 'latency_ms'),
        Index('idx_prediction_logs_status_code', 'status_code'),
        Index('idx_prediction_logs_user_id', 'user_id'),
        Index('idx_prediction_logs_model_run_id', 'model_run_id'),
        Index('idx_prediction_logs_is_flagged', 'is_flagged'),
    )

    @validates('status_code')
    def validate_status_code(self, key, status_code):
        """Validate HTTP status codes."""
        if status_code and (status_code < 100 or status_code > 599):
            raise ValueError("Status code must be a valid HTTP status code (100-599)")
        return status_code

    def __repr__(self):
        return f"<PredictionLog(id={self.id}, model_name='{self.model_name}', status_code={self.status_code})>"


class DataDriftMonitoring(Base):
    """Model for tracking data drift over time."""

    __tablename__ = "data_drift_monitoring"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Model and time information
    model_name = Column(String(255), nullable=False)
    model_version = Column(String(100), nullable=False)
    window_start = Column(DateTime, nullable=False)
    window_end = Column(DateTime, nullable=False)

    # Drift metrics
    drift_score = Column(Float, nullable=False)
    drift_threshold = Column(Float, default=0.1)
    is_drift_detected = Column(Boolean, default=False)

    # Feature-level drift
    feature_drift_scores = Column(JSON, default=dict)
    drifted_features = Column(JSON, default=list)

    # Statistical measures
    psi_score = Column(Float)  # Population Stability Index
    kl_divergence = Column(Float)  # Kullback-Leibler divergence
    js_divergence = Column(Float)  # Jensen-Shannon divergence

    # Reference data info
    reference_period_start = Column(DateTime)
    reference_period_end = Column(DateTime)
    reference_data_size = Column(Integer)
    current_data_size = Column(Integer)

    # Metadata
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    detection_method = Column(String(100))  # psi, ks_test, chi2_test, etc.

    # Indexes
    __table_args__ = (
        Index('idx_drift_monitoring_model_name', 'model_name'),
        Index('idx_drift_monitoring_window_start', 'window_start'),
        Index('idx_drift_monitoring_is_drift_detected', 'is_drift_detected'),
        Index('idx_drift_monitoring_model_time', 'model_name', 'window_start'),
    )

    def __repr__(self):
        return f"<DataDriftMonitoring(model_name='{self.model_name}', drift_score={self.drift_score}, is_drift_detected={self.is_drift_detected})>"