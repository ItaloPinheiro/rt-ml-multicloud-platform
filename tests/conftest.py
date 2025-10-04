"""Pytest configuration and shared fixtures."""

import os
import tempfile
import asyncio
from datetime import datetime, timezone
from typing import Generator, Dict, Any
import pytest
import pytest_asyncio
import redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Test configuration
os.environ["ENVIRONMENT"] = "test"


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def test_config():
    """Test configuration fixture."""
    from src.utils.config import Config, DatabaseConfig, RedisConfig, MLflowConfig, APIConfig, MonitoringConfig

    return Config(
        environment="test",
        debug=True,
        database=DatabaseConfig(
            host="sqlite",
            port=0,
            database=":memory:",
            username="",
            password="",
            ssl_mode="disable"
        ),
        redis=RedisConfig(
            host="localhost",
            port=6379,
            password=None,
            db=1  # Use different DB for tests
        ),
        mlflow=MLflowConfig(
            tracking_uri="sqlite:///test_mlflow.db",
            experiment_name="test_experiment"
        ),
        api=APIConfig(
            host="127.0.0.1",
            port=8001,
            debug=True
        ),
        monitoring=MonitoringConfig(
            prometheus_enabled=False,
            grafana_enabled=False,
            log_level="DEBUG"
        )
    )


@pytest.fixture
def test_database(test_config):
    """Create test database with tables."""
    from src.database.session import DatabaseManager
    from src.database.models import Base

    db_manager = DatabaseManager(test_config.database)
    db_manager.initialize()

    # Create all tables
    Base.metadata.create_all(bind=db_manager.engine)

    yield db_manager

    # Cleanup
    db_manager.close()


@pytest.fixture
def db_session(test_database):
    """Create database session for tests."""
    session = test_database.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture
def mock_redis():
    """Mock Redis client for tests."""
    try:
        # Try to connect to real Redis if available
        client = redis.Redis(host="localhost", port=6379, db=1, decode_responses=False)
        client.ping()

        # Clear test database
        client.flushdb()

        yield client

        # Cleanup
        client.flushdb()

    except (redis.ConnectionError, redis.TimeoutError):
        # Use fakeredis if Redis is not available
        try:
            import fakeredis
            client = fakeredis.FakeRedis(decode_responses=False)
            yield client
        except ImportError:
            pytest.skip("Redis not available and fakeredis not installed")


@pytest.fixture
def sample_features():
    """Sample feature data for tests."""
    return {
        "amount": 250.00,
        "merchant_category": "electronics",
        "hour_of_day": 14,
        "is_weekend": False,
        "risk_score": 0.3,
        "user_age": 35,
        "transaction_count_24h": 3
    }


@pytest.fixture
def sample_prediction_request():
    """Sample prediction request data."""
    return {
        "features": {
            "amount": 250.00,
            "merchant_category": "electronics",
            "hour_of_day": 14,
            "is_weekend": False,
            "risk_score": 0.3
        },
        "model_name": "fraud_detector",
        "version": "latest",
        "return_probabilities": True
    }


@pytest.fixture
def sample_batch_prediction_request():
    """Sample batch prediction request data."""
    return {
        "instances": [
            {
                "amount": 250.00,
                "merchant_category": "electronics",
                "hour_of_day": 14,
                "is_weekend": False,
                "risk_score": 0.3
            },
            {
                "amount": 50.00,
                "merchant_category": "grocery",
                "hour_of_day": 10,
                "is_weekend": True,
                "risk_score": 0.1
            }
        ],
        "model_name": "fraud_detector",
        "version": "latest",
        "return_probabilities": True
    }


@pytest.fixture
def sample_stream_message():
    """Sample stream message for ingestion tests."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": "user_123",
        "transaction_id": "txn_456",
        "data": {
            "amount": 100.0,
            "merchant": "Test Merchant",
            "category": "retail"
        }
    }


@pytest.fixture
def mock_mlflow_client():
    """Mock MLflow client for tests."""
    class MockMLflowClient:
        def __init__(self):
            self.experiments = {}
            self.runs = {}
            self.models = {}

        def create_experiment(self, name, artifact_location=None):
            exp_id = str(len(self.experiments) + 1)
            self.experiments[exp_id] = {
                "experiment_id": exp_id,
                "name": name,
                "artifact_location": artifact_location,
                "lifecycle_stage": "active"
            }
            return exp_id

        def get_experiment_by_name(self, name):
            for exp in self.experiments.values():
                if exp["name"] == name:
                    return exp
            return None

        def list_experiments(self, max_results=None):
            return list(self.experiments.values())[:max_results] if max_results else list(self.experiments.values())

        def create_run(self, experiment_id, start_time=None, tags=None):
            run_id = f"run_{len(self.runs) + 1}"
            self.runs[run_id] = {
                "info": {
                    "run_id": run_id,
                    "experiment_id": experiment_id,
                    "status": "RUNNING",
                    "start_time": start_time or datetime.now(timezone.utc).timestamp() * 1000,
                    "artifact_uri": f"file:///tmp/mlruns/{experiment_id}/{run_id}/artifacts"
                },
                "data": {
                    "params": {},
                    "metrics": {},
                    "tags": tags or {}
                }
            }
            return self.runs[run_id]

        def log_param(self, run_id, key, value):
            if run_id in self.runs:
                self.runs[run_id]["data"]["params"][key] = value

        def log_metric(self, run_id, key, value, timestamp=None, step=None):
            if run_id in self.runs:
                self.runs[run_id]["data"]["metrics"][key] = value

        def end_run(self, run_id, status="FINISHED"):
            if run_id in self.runs:
                self.runs[run_id]["info"]["status"] = status
                self.runs[run_id]["info"]["end_time"] = datetime.now(timezone.utc).timestamp() * 1000

    return MockMLflowClient()


@pytest.fixture
def feature_store_client(test_config, mock_redis, test_database):
    """Feature store client for tests."""
    from src.feature_store.store import FeatureStore
    from src.feature_store.client import FeatureStoreClient
    import src.database.session as session_module

    # Set the global database manager
    session_module._db_manager = test_database

    feature_store = FeatureStore(redis_client=mock_redis)
    client = FeatureStoreClient(feature_store=feature_store)

    # Setup common transforms
    client.setup_common_transforms()

    return client


@pytest.fixture
def metrics_collector():
    """Metrics collector for tests."""
    from src.monitoring.metrics import MetricsCollector

    collector = MetricsCollector()
    yield collector

    # Cleanup
    collector.clear_metrics()


@pytest.fixture
def health_checker():
    """Health checker for tests."""
    from src.monitoring.health import HealthChecker

    checker = HealthChecker()
    yield checker

    # Cleanup
    if checker.running:
        asyncio.create_task(checker.stop())


@pytest.fixture
def alert_manager():
    """Alert manager for tests."""
    from src.monitoring.alerts import AlertManager

    manager = AlertManager(evaluation_interval_seconds=1.0)  # Fast evaluation for tests
    yield manager

    # Cleanup
    if manager.running:
        asyncio.create_task(manager.stop())


# Async fixtures
@pytest_asyncio.fixture
async def async_feature_store_client(test_config, mock_redis):
    """Async feature store client for tests."""
    from src.feature_store.store import FeatureStore
    from src.feature_store.client import FeatureStoreClient

    feature_store = FeatureStore(redis_client=mock_redis)
    client = FeatureStoreClient(feature_store=feature_store)

    # Setup common transforms
    client.setup_common_transforms()

    yield client


@pytest_asyncio.fixture
async def async_health_checker():
    """Async health checker for tests."""
    from src.monitoring.health import HealthChecker

    checker = HealthChecker()
    await checker.start()

    yield checker

    await checker.stop()


@pytest_asyncio.fixture
async def async_alert_manager():
    """Async alert manager for tests."""
    from src.monitoring.alerts import AlertManager

    manager = AlertManager(evaluation_interval_seconds=0.1)  # Very fast for tests
    await manager.start()

    yield manager

    await manager.stop()


# Utility functions for tests
def assert_approximately_equal(actual, expected, tolerance=0.01):
    """Assert that two values are approximately equal within tolerance."""
    assert abs(actual - expected) <= tolerance, f"Expected {expected}, got {actual} (tolerance: {tolerance})"


def create_test_model_artifact(temp_dir: str, model_name: str = "test_model"):
    """Create a test model artifact for testing."""
    import pickle
    import os

    # Create a simple sklearn model
    try:
        from sklearn.linear_model import LogisticRegression
        import numpy as np

        # Create and train a simple model
        X = np.random.random((100, 5))
        y = np.random.randint(0, 2, 100)
        model = LogisticRegression()
        model.fit(X, y)

        # Save model
        model_path = os.path.join(temp_dir, f"{model_name}.pkl")
        with open(model_path, "wb") as f:
            pickle.dump(model, f)

        return model_path

    except ImportError:
        # Fallback: create a dummy model
        class DummyModel:
            def predict(self, X):
                return [0] * len(X)

            def predict_proba(self, X):
                return [[0.7, 0.3]] * len(X)

        model = DummyModel()
        model_path = os.path.join(temp_dir, f"{model_name}.pkl")
        with open(model_path, "wb") as f:
            pickle.dump(model, f)

        return model_path