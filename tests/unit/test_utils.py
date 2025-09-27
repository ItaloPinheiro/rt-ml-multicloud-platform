"""Unit tests for utility modules."""

import os
import tempfile
import pytest
from unittest.mock import patch, mock_open

from src.utils.config import (
    Config, DatabaseConfig, RedisConfig, MLflowConfig, ConfigManager, get_config, validate_config
)
from src.utils.logging import (
    setup_logging, get_logger, log_function_call, log_performance, LogContext,
    configure_ml_pipeline_logging, CustomJSONFormatter
)


class TestConfigManager:
    """Test configuration management functionality."""

    def test_default_config_creation(self):
        """Test creating default configuration."""
        config = Config()

        assert config.environment == "development"
        assert config.debug is False
        assert config.redis is not None
        assert config.api is not None
        assert config.monitoring is not None

    def test_database_config_creation(self):
        """Test database configuration."""
        db_config = DatabaseConfig(
            host="localhost",
            port=5432,
            database="test_db",
            username="test_user",
            password="test_pass"
        )

        assert db_config.host == "localhost"
        assert db_config.port == 5432
        assert db_config.ssl_mode == "require"  # Default value
        assert db_config.max_connections == 20

    def test_redis_config_creation(self):
        """Test Redis configuration."""
        redis_config = RedisConfig(
            host="redis-server",
            port=6380,
            password="secret",
            db=2
        )

        assert redis_config.host == "redis-server"
        assert redis_config.port == 6380
        assert redis_config.password == "secret"
        assert redis_config.db == 2

    def test_mlflow_config_creation(self):
        """Test MLflow configuration."""
        mlflow_config = MLflowConfig(
            tracking_uri="http://localhost:5000",
            experiment_name="test_experiment",
            default_tags={"env": "test"}
        )

        assert mlflow_config.tracking_uri == "http://localhost:5000"
        assert mlflow_config.experiment_name == "test_experiment"
        assert mlflow_config.default_tags["env"] == "test"

    def test_config_manager_load_from_environment(self):
        """Test loading configuration from environment variables."""
        env_vars = {
            "ENVIRONMENT": "production",
            "DEBUG": "true",
            "DATABASE_HOST": "prod-db",
            "DATABASE_PORT": "5433",
            "DATABASE_NAME": "prod_ml",
            "DATABASE_USER": "prod_user",
            "DATABASE_PASSWORD": "prod_pass",
            "REDIS_HOST": "prod-redis",
            "REDIS_PORT": "6380",
            "MLFLOW_TRACKING_URI": "http://prod-mlflow:5000"
        }

        with patch.dict(os.environ, env_vars):
            manager = ConfigManager()
            config = manager.load_config()

            assert config.environment == "production"
            assert config.debug is True
            assert config.database.host == "prod-db"
            assert config.database.port == 5433
            assert config.redis.host == "prod-redis"
            assert config.mlflow.tracking_uri == "http://prod-mlflow:5000"

    def test_config_manager_load_from_file(self, temp_dir):
        """Test loading configuration from YAML file."""
        config_content = """
environment: staging
debug: false
database:
  host: staging-db
  port: 5432
  database: staging_ml
  username: staging_user
  password: staging_pass
redis:
  host: staging-redis
  port: 6379
mlflow:
  tracking_uri: http://staging-mlflow:5000
  experiment_name: staging_experiment
"""
        config_file = os.path.join(temp_dir, "config.yaml")
        with open(config_file, "w") as f:
            f.write(config_content)

        manager = ConfigManager(config_path=config_file)
        config = manager.load_config()

        assert config.environment == "staging"
        assert config.debug is False
        assert config.database.host == "staging-db"
        assert config.redis.host == "staging-redis"
        assert config.mlflow.tracking_uri == "http://staging-mlflow:5000"

    def test_config_validation_success(self):
        """Test successful configuration validation."""
        config = Config(
            environment="production",
            mlflow=MLflowConfig(tracking_uri="http://localhost:5000"),
            redis=RedisConfig()
        )

        assert validate_config(config) is True

    def test_config_validation_missing_mlflow(self):
        """Test configuration validation with missing MLflow in production."""
        config = Config(environment="production")

        with pytest.raises(ValueError, match="MLflow tracking URI is required in production"):
            validate_config(config)

    def test_config_validation_missing_redis(self):
        """Test configuration validation with missing Redis in production."""
        config = Config(
            environment="production",
            mlflow=MLflowConfig(tracking_uri="http://localhost:5000"),
            redis=None
        )

        with pytest.raises(ValueError, match="Redis configuration is required in production"):
            validate_config(config)

    def test_config_validation_invalid_port(self):
        """Test configuration validation with invalid port."""
        config = Config(
            api=type('APIConfig', (), {'port': 70000})()  # Invalid port
        )

        with pytest.raises(ValueError, match="API port must be between 1 and 65535"):
            validate_config(config)

    def test_config_validation_negative_values(self):
        """Test configuration validation with negative values."""
        config = Config(feature_store_ttl=-1)

        with pytest.raises(ValueError, match="Feature store TTL must be non-negative"):
            validate_config(config)

    def test_deep_merge(self):
        """Test deep merge functionality."""
        manager = ConfigManager()

        base = {
            "level1": {
                "level2": {
                    "key1": "value1",
                    "key2": "value2"
                }
            },
            "simple_key": "simple_value"
        }

        override = {
            "level1": {
                "level2": {
                    "key2": "new_value2",
                    "key3": "value3"
                }
            },
            "new_simple_key": "new_simple_value"
        }

        result = manager._deep_merge(base, override)

        assert result["level1"]["level2"]["key1"] == "value1"  # Preserved
        assert result["level1"]["level2"]["key2"] == "new_value2"  # Overridden
        assert result["level1"]["level2"]["key3"] == "value3"  # Added
        assert result["simple_key"] == "simple_value"  # Preserved
        assert result["new_simple_key"] == "new_simple_value"  # Added


class TestLogging:
    """Test logging utilities."""

    def test_custom_json_formatter(self):
        """Test custom JSON formatter."""
        import logging
        import json

        formatter = CustomJSONFormatter()

        # Create a log record
        logger = logging.getLogger("test")
        record = logger.makeRecord(
            name="test",
            level=logging.INFO,
            fn="test.py",
            lno=10,
            msg="Test message",
            args=(),
            exc_info=None
        )

        # Format the record
        formatted = formatter.format(record)
        log_data = json.loads(formatted)

        assert log_data["level"] == "INFO"
        assert log_data["logger"] == "test"
        assert log_data["message"] == "Test message"
        assert log_data["module"] == "test_utils"
        assert "timestamp" in log_data

    def test_custom_json_formatter_with_extra(self):
        """Test custom JSON formatter with extra fields."""
        import logging
        import json

        formatter = CustomJSONFormatter()

        logger = logging.getLogger("test")
        record = logger.makeRecord(
            name="test",
            level=logging.ERROR,
            fn="test.py",
            lno=10,
            msg="Error message",
            args=(),
            exc_info=None
        )

        # Add extra fields
        record.user_id = "user_123"
        record.request_id = "req_456"

        formatted = formatter.format(record)
        log_data = json.loads(formatted)

        assert log_data["user_id"] == "user_123"
        assert log_data["request_id"] == "req_456"

    def test_setup_logging_simple_format(self):
        """Test logging setup with simple format."""
        import logging

        setup_logging(
            level="DEBUG",
            format_type="simple",
            enable_console=True,
            service_name="test_service"
        )

        logger = logging.getLogger("test")
        assert logger.level <= logging.DEBUG

    def test_get_logger(self):
        """Test get_logger function."""
        logger = get_logger("test_module")
        assert logger is not None

    def test_log_function_call_decorator(self):
        """Test log_function_call decorator."""
        @log_function_call
        def test_function(x, y, keyword_arg="default"):
            return x + y

        result = test_function(1, 2, keyword_arg="test")
        assert result == 3

    def test_log_function_call_decorator_with_exception(self):
        """Test log_function_call decorator with exception."""
        @log_function_call
        def failing_function():
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            failing_function()

    def test_log_performance_decorator(self):
        """Test log_performance decorator."""
        @log_performance("test_operation")
        def test_operation():
            return "success"

        result = test_operation()
        assert result == "success"

    def test_log_performance_decorator_with_exception(self):
        """Test log_performance decorator with exception."""
        @log_performance("failing_operation")
        def failing_operation():
            raise RuntimeError("Operation failed")

        with pytest.raises(RuntimeError, match="Operation failed"):
            failing_operation()

    def test_log_context_manager(self):
        """Test LogContext context manager."""
        # This test requires structlog to be available
        try:
            import structlog

            with LogContext(user_id="user_123", request_id="req_456"):
                # Context should be bound
                pass
            # Context should be restored

        except ImportError:
            pytest.skip("structlog not available")

    def test_configure_ml_pipeline_logging(self):
        """Test ML pipeline logging configuration."""
        configure_ml_pipeline_logging(
            environment="test",
            service_name="test_pipeline"
        )

        # Should not raise any exceptions
        logger = get_logger("test")
        assert logger is not None

    @patch("src.utils.logging.structlog")
    def test_setup_logging_without_structlog(self, mock_structlog):
        """Test logging setup when structlog is not available."""
        mock_structlog.configure.side_effect = AttributeError("No structlog")

        # Should fall back to standard logging
        setup_logging(
            level="INFO",
            format_type="json",
            enable_console=True
        )

    def test_setup_request_logging_with_contextvars(self):
        """Test request logging setup with contextvars."""
        try:
            from src.utils.logging import setup_request_logging
            request_id_var = setup_request_logging()
            assert request_id_var is not None
        except ImportError:
            pytest.skip("contextvars not available in this Python version")

    def test_setup_request_logging_fallback(self):
        """Test request logging setup fallback to thread-local."""
        with patch("src.utils.logging.ContextVar", side_effect=ImportError):
            from src.utils.logging import setup_request_logging
            request_context = setup_request_logging()
            assert request_context is not None

    def test_logging_file_creation(self, temp_dir):
        """Test log file creation."""
        log_file = os.path.join(temp_dir, "test.log")

        setup_logging(
            level="INFO",
            format_type="simple",
            log_file=log_file,
            enable_console=False
        )

        # Log a message
        logger = get_logger("test")
        logger.info("Test log message")

        # Verify file was created
        assert os.path.exists(log_file)

    def test_logging_with_service_context(self):
        """Test logging with service context."""
        setup_logging(
            level="DEBUG",
            service_name="test_service",
            environment="test"
        )

        logger = get_logger("test")
        logger.info("Test message with context")

        # Should not raise any exceptions