"""Configuration management utilities.

This module provides utilities for loading and managing configuration
from environment variables, files, and cloud services.
"""

import os
import json
import yaml
from typing import Dict, Any, Optional, Union
from pathlib import Path
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


@dataclass
class DatabaseConfig:
    """Database configuration."""
    host: str
    port: int
    database: str
    username: str
    password: str
    ssl_mode: str = "require"
    connection_timeout: int = 30
    max_connections: int = 20


@dataclass
class RedisConfig:
    """Redis configuration."""
    host: str = "localhost"
    port: int = 6379
    password: Optional[str] = None
    db: int = 0
    socket_timeout: int = 5
    socket_connect_timeout: int = 5
    max_connections: int = 50
    retry_on_timeout: bool = True


@dataclass
class MLflowConfig:
    """MLflow configuration."""
    tracking_uri: str
    registry_uri: Optional[str] = None
    experiment_name: str = "default"
    artifact_location: Optional[str] = None
    default_tags: Dict[str, str] = field(default_factory=dict)


@dataclass
class KafkaConfig:
    """Kafka configuration."""
    bootstrap_servers: str
    security_protocol: str = "PLAINTEXT"
    sasl_mechanism: Optional[str] = None
    sasl_username: Optional[str] = None
    sasl_password: Optional[str] = None
    ssl_ca_location: Optional[str] = None
    ssl_certificate_location: Optional[str] = None
    ssl_key_location: Optional[str] = None


@dataclass
class PubSubConfig:
    """Google Cloud Pub/Sub configuration."""
    project_id: str
    credentials_path: Optional[str] = None
    emulator_host: Optional[str] = None


@dataclass
class KinesisConfig:
    """AWS Kinesis configuration."""
    region: str = "us-east-1"
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None
    session_token: Optional[str] = None
    endpoint_url: Optional[str] = None


@dataclass
class APIConfig:
    """API server configuration."""
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    reload: bool = False
    debug: bool = False
    cors_origins: list = field(default_factory=lambda: ["*"])
    max_request_size: int = 16 * 1024 * 1024  # 16MB
    timeout: int = 30


@dataclass
class MonitoringConfig:
    """Monitoring configuration."""
    prometheus_enabled: bool = True
    prometheus_port: int = 9090
    grafana_enabled: bool = True
    grafana_port: int = 3001
    log_level: str = "INFO"
    structured_logging: bool = True


@dataclass
class Config:
    """Main application configuration."""
    environment: str = "development"
    debug: bool = False

    # Service configurations
    database: Optional[DatabaseConfig] = None
    redis: RedisConfig = field(default_factory=RedisConfig)
    mlflow: Optional[MLflowConfig] = None
    kafka: Optional[KafkaConfig] = None
    pubsub: Optional[PubSubConfig] = None
    kinesis: Optional[KinesisConfig] = None
    api: APIConfig = field(default_factory=APIConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)

    # Additional settings
    feature_store_ttl: int = 3600
    model_cache_size: int = 10
    batch_size: int = 1000
    max_retries: int = 3

    # Custom settings
    custom: Dict[str, Any] = field(default_factory=dict)


class ConfigManager:
    """Configuration manager for loading from various sources."""

    def __init__(self, config_path: Optional[str] = None):
        """Initialize configuration manager.

        Args:
            config_path: Optional path to configuration file
        """
        self.config_path = config_path
        self.logger = logger.bind(component="ConfigManager")

    def load_config(self, environment: Optional[str] = None) -> Config:
        """Load configuration from environment and files.

        Args:
            environment: Environment name (development, staging, production)

        Returns:
            Loaded configuration object
        """
        environment = environment or os.getenv("ENVIRONMENT", "development")

        # Start with default config
        config_dict = {"environment": environment}

        # Load from file if specified
        if self.config_path and Path(self.config_path).exists():
            file_config = self._load_config_file(self.config_path)
            config_dict.update(file_config)
            # Update environment from file if specified
            environment = config_dict.get("environment", environment)

        # Load environment-specific config
        env_config_path = f"configs/{environment}.yaml"
        if Path(env_config_path).exists():
            env_config = self._load_config_file(env_config_path)
            config_dict.update(env_config)

        # Override with environment variables
        env_config = self._load_from_environment()
        config_dict = self._deep_merge(config_dict, env_config)

        # Create configuration object
        config = self._dict_to_config(config_dict)

        self.logger.info(
            "Configuration loaded",
            environment=environment,
            config_sources=self._get_config_sources()
        )

        return config

    def _load_config_file(self, file_path: str) -> Dict[str, Any]:
        """Load configuration from file.

        Args:
            file_path: Path to configuration file

        Returns:
            Configuration dictionary
        """
        try:
            with open(file_path, 'r') as f:
                if file_path.endswith('.yaml') or file_path.endswith('.yml'):
                    return yaml.safe_load(f) or {}
                elif file_path.endswith('.json'):
                    return json.load(f)
                else:
                    raise ValueError(f"Unsupported config file format: {file_path}")

        except Exception as e:
            self.logger.error(f"Failed to load config file: {file_path}", error=str(e))
            return {}

    def _load_from_environment(self) -> Dict[str, Any]:
        """Load configuration from environment variables.

        Returns:
            Configuration dictionary from environment
        """
        config = {}

        # General settings
        if os.getenv("DEBUG"):
            config["debug"] = os.getenv("DEBUG").lower() == "true"

        # Database configuration
        if os.getenv("DATABASE_HOST"):
            config["database"] = {
                "host": os.getenv("DATABASE_HOST"),
                "port": int(os.getenv("DATABASE_PORT", "5432")),
                "database": os.getenv("DATABASE_NAME", "ml_pipeline"),
                "username": os.getenv("DATABASE_USER", "postgres"),
                "password": os.getenv("DATABASE_PASSWORD", ""),
                "ssl_mode": os.getenv("DATABASE_SSL_MODE", "require"),
            }

        # Redis configuration
        redis_config = {}
        if os.getenv("REDIS_HOST"):
            redis_config["host"] = os.getenv("REDIS_HOST")
        if os.getenv("REDIS_PORT"):
            redis_config["port"] = int(os.getenv("REDIS_PORT"))
        if os.getenv("REDIS_PASSWORD"):
            redis_config["password"] = os.getenv("REDIS_PASSWORD")
        if os.getenv("REDIS_DB"):
            redis_config["db"] = int(os.getenv("REDIS_DB"))

        if redis_config:
            config["redis"] = redis_config

        # MLflow configuration
        if os.getenv("MLFLOW_TRACKING_URI"):
            config["mlflow"] = {
                "tracking_uri": os.getenv("MLFLOW_TRACKING_URI"),
                "registry_uri": os.getenv("MLFLOW_REGISTRY_URI"),
                "experiment_name": os.getenv("MLFLOW_EXPERIMENT_NAME", "default"),
                "artifact_location": os.getenv("MLFLOW_ARTIFACT_ROOT"),
            }

        # Kafka configuration
        if os.getenv("KAFKA_BOOTSTRAP_SERVERS"):
            config["kafka"] = {
                "bootstrap_servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS"),
                "security_protocol": os.getenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT"),
                "sasl_mechanism": os.getenv("KAFKA_SASL_MECHANISM"),
                "sasl_username": os.getenv("KAFKA_SASL_USERNAME"),
                "sasl_password": os.getenv("KAFKA_SASL_PASSWORD"),
            }

        # Pub/Sub configuration
        if os.getenv("GCP_PROJECT"):
            config["pubsub"] = {
                "project_id": os.getenv("GCP_PROJECT"),
                "credentials_path": os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
                "emulator_host": os.getenv("PUBSUB_EMULATOR_HOST"),
            }

        # Kinesis configuration
        if os.getenv("AWS_REGION"):
            config["kinesis"] = {
                "region": os.getenv("AWS_REGION"),
                "access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
                "secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
                "session_token": os.getenv("AWS_SESSION_TOKEN"),
                "endpoint_url": os.getenv("AWS_KINESIS_ENDPOINT_URL"),
            }

        # API configuration
        api_config = {}
        if os.getenv("API_HOST"):
            api_config["host"] = os.getenv("API_HOST")
        if os.getenv("API_PORT"):
            api_config["port"] = int(os.getenv("API_PORT"))
        if os.getenv("API_WORKERS"):
            api_config["workers"] = int(os.getenv("API_WORKERS"))
        if os.getenv("API_RELOAD"):
            api_config["reload"] = os.getenv("API_RELOAD").lower() == "true"
        if os.getenv("API_DEBUG"):
            api_config["debug"] = os.getenv("API_DEBUG").lower() == "true"
        if os.getenv("CORS_ORIGINS"):
            api_config["cors_origins"] = os.getenv("CORS_ORIGINS").split(",")

        if api_config:
            config["api"] = api_config

        # Monitoring configuration
        monitoring_config = {}
        if os.getenv("LOG_LEVEL"):
            monitoring_config["log_level"] = os.getenv("LOG_LEVEL")
        if os.getenv("PROMETHEUS_ENABLED"):
            monitoring_config["prometheus_enabled"] = os.getenv("PROMETHEUS_ENABLED").lower() == "true"
        if os.getenv("GRAFANA_ENABLED"):
            monitoring_config["grafana_enabled"] = os.getenv("GRAFANA_ENABLED").lower() == "true"

        if monitoring_config:
            config["monitoring"] = monitoring_config

        # Additional settings
        if os.getenv("FEATURE_STORE_TTL"):
            config["feature_store_ttl"] = int(os.getenv("FEATURE_STORE_TTL"))
        if os.getenv("MODEL_CACHE_SIZE"):
            config["model_cache_size"] = int(os.getenv("MODEL_CACHE_SIZE"))
        if os.getenv("BATCH_SIZE"):
            config["batch_size"] = int(os.getenv("BATCH_SIZE"))
        if os.getenv("MAX_RETRIES"):
            config["max_retries"] = int(os.getenv("MAX_RETRIES"))

        return config

    def _dict_to_config(self, config_dict: Dict[str, Any]) -> Config:
        """Convert dictionary to Config object.

        Args:
            config_dict: Configuration dictionary

        Returns:
            Config object
        """
        # Extract sub-configurations
        database_config = None
        if "database" in config_dict:
            database_config = DatabaseConfig(**config_dict["database"])

        redis_config = RedisConfig()
        if "redis" in config_dict:
            redis_dict = config_dict["redis"]
            redis_config = RedisConfig(**redis_dict)

        mlflow_config = None
        if "mlflow" in config_dict:
            mlflow_config = MLflowConfig(**config_dict["mlflow"])

        kafka_config = None
        if "kafka" in config_dict:
            kafka_config = KafkaConfig(**config_dict["kafka"])

        pubsub_config = None
        if "pubsub" in config_dict:
            pubsub_config = PubSubConfig(**config_dict["pubsub"])

        kinesis_config = None
        if "kinesis" in config_dict:
            kinesis_config = KinesisConfig(**config_dict["kinesis"])

        api_config = APIConfig()
        if "api" in config_dict:
            api_dict = config_dict["api"]
            api_config = APIConfig(**api_dict)

        monitoring_config = MonitoringConfig()
        if "monitoring" in config_dict:
            monitoring_dict = config_dict["monitoring"]
            monitoring_config = MonitoringConfig(**monitoring_dict)

        # Create main config
        main_config = {
            "environment": config_dict.get("environment", "development"),
            "debug": config_dict.get("debug", False),
            "database": database_config,
            "redis": redis_config,
            "mlflow": mlflow_config,
            "kafka": kafka_config,
            "pubsub": pubsub_config,
            "kinesis": kinesis_config,
            "api": api_config,
            "monitoring": monitoring_config,
            "feature_store_ttl": config_dict.get("feature_store_ttl", 3600),
            "model_cache_size": config_dict.get("model_cache_size", 10),
            "batch_size": config_dict.get("batch_size", 1000),
            "max_retries": config_dict.get("max_retries", 3),
            "custom": config_dict.get("custom", {})
        }

        return Config(**main_config)

    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge two dictionaries.

        Args:
            base: Base dictionary
            override: Override dictionary

        Returns:
            Merged dictionary
        """
        result = base.copy()

        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value

        return result

    def _get_config_sources(self) -> list:
        """Get list of configuration sources used.

        Returns:
            List of configuration sources
        """
        sources = ["environment_variables"]

        if self.config_path and Path(self.config_path).exists():
            sources.append(f"file:{self.config_path}")

        return sources


def get_config(config_path: Optional[str] = None, environment: Optional[str] = None) -> Config:
    """Get application configuration.

    Args:
        config_path: Optional path to configuration file
        environment: Environment name

    Returns:
        Configuration object
    """
    manager = ConfigManager(config_path)
    return manager.load_config(environment)


def validate_config(config: Config) -> bool:
    """Validate configuration object.

    Args:
        config: Configuration to validate

    Returns:
        True if valid, raises exception if invalid
    """
    # Validate required configurations based on environment
    if config.environment == "production":
        if not config.mlflow or not config.mlflow.tracking_uri:
            raise ValueError("MLflow tracking URI is required in production")

        if not config.redis:
            raise ValueError("Redis configuration is required in production")

    # Validate API configuration
    if config.api.port < 1 or config.api.port > 65535:
        raise ValueError("API port must be between 1 and 65535")

    # Validate Redis configuration
    if config.redis.port < 1 or config.redis.port > 65535:
        raise ValueError("Redis port must be between 1 and 65535")

    # Validate timeouts and limits
    if config.feature_store_ttl < 0:
        raise ValueError("Feature store TTL must be non-negative")

    if config.model_cache_size < 1:
        raise ValueError("Model cache size must be at least 1")

    if config.batch_size < 1:
        raise ValueError("Batch size must be at least 1")

    if config.max_retries < 0:
        raise ValueError("Max retries must be non-negative")

    return True