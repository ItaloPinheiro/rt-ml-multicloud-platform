"""Apache Beam transforms for feature engineering.

This module provides production-ready transforms for extracting and
aggregating features from streaming data using Apache Beam.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Tuple

import numpy as np

try:
    import apache_beam as beam
    from apache_beam.pvalue import TaggedOutput
except ImportError:
    beam = None
    TaggedOutput = None

import structlog

logger = structlog.get_logger()


class FeatureExtraction(beam.DoFn):
    """Extract features from raw streaming data.

    This transform handles feature extraction from various data formats
    and produces standardized feature vectors for ML models.
    """

    def __init__(self, feature_config: Optional[Dict[str, Any]] = None):
        """Initialize feature extraction transform.

        Args:
            feature_config: Configuration for feature extraction including:
                - domain: Feature extraction domain ("transaction", "generic").
                  Defaults to "transaction" for backward compatibility.
        """
        if beam is None:
            raise ImportError(
                "apache-beam is required for feature engineering. "
                "Install with: pip install apache-beam"
            )

        self.feature_config = feature_config or {}
        self.domain = self.feature_config.get("domain", "transaction")
        self.logger = logger.bind(component="FeatureExtraction", domain=self.domain)

    def setup(self):
        """Setup method called once per worker."""
        # Initialize any heavy resources here
        self.logger.info("FeatureExtraction transform initialized")

    def process(self, element: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
        """Extract features from a single element.

        Args:
            element: Input data element (typically a stream message)

        Yields:
            Dict[str, Any]: Extracted features
        """
        try:
            # Handle different input formats
            if isinstance(element, str):
                element = json.loads(element)
            elif not isinstance(element, dict):
                element = {"raw_data": str(element)}

            # Extract data from message wrapper if present
            data = element.get("data", element)
            message_id = element.get("message_id", "unknown")
            timestamp = element.get("timestamp", datetime.now(timezone.utc).isoformat())

            # Convert timestamp to datetime if it's a string
            if isinstance(timestamp, str):
                try:
                    timestamp_dt = datetime.fromisoformat(
                        timestamp.replace("Z", "+00:00")
                    )
                except ValueError:
                    timestamp_dt = datetime.now(timezone.utc)
            else:
                timestamp_dt = timestamp

            # Extract basic features
            features = {
                "message_id": message_id,
                "timestamp": timestamp_dt.isoformat(),
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }

            # Extract domain-specific features based on configured domain
            domain_extractors = {
                "transaction": self._extract_transaction_features,
                "generic": self._extract_generic_features,
            }
            extractor = domain_extractors.get(
                self.domain, self._extract_transaction_features
            )
            features.update(extractor(data))

            # These are domain-agnostic and always applied
            features.update(self._extract_temporal_features(timestamp_dt))
            features.update(self._extract_categorical_features(data))
            features.update(self._extract_numerical_features(data))

            # Add computed features
            features.update(self._compute_derived_features(features))

            # Validate features
            features = self._validate_features(features)

            yield features

        except Exception as e:
            # Log error and yield to error output
            error_info = {
                "error": str(e),
                "element": str(element)[:1000],  # Truncate large elements
                "transform": "FeatureExtraction",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            self.logger.error(
                "Feature extraction failed",
                error=str(e),
                element_type=type(element).__name__,
            )

            yield TaggedOutput("errors", error_info)

    def _extract_transaction_features(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract transaction-specific features.

        Args:
            data: Input data dictionary

        Returns:
            Dictionary of transaction features
        """
        features = {}

        # Amount-related features
        amount = data.get("amount", 0)
        if amount is not None:
            try:
                amount = float(amount)
                features["amount"] = amount
                features["amount_log"] = np.log1p(amount) if amount > 0 else 0
                features["is_high_amount"] = amount > 500
                features["amount_rounded"] = round(amount, 2)
                features["amount_category"] = self._categorize_amount(amount)
            except (ValueError, TypeError):
                features["amount"] = 0
                features["amount_log"] = 0
                features["is_high_amount"] = False

        # Merchant and category features
        features["merchant_category"] = data.get("merchant_category", "unknown")
        features["merchant_id"] = data.get("merchant_id", "unknown")
        features["merchant_name"] = data.get("merchant_name", "unknown")

        # User features
        features["user_id"] = data.get("user_id", "unknown")
        features["account_id"] = data.get("account_id", "unknown")

        # Transaction type features
        features["transaction_type"] = data.get("transaction_type", "unknown")
        features["payment_method"] = data.get("payment_method", "unknown")
        features["currency"] = data.get("currency", "USD")

        return features

    def _extract_generic_features(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract features generically from flat key-value data.

        Passes through all numeric and string values without
        domain-specific assumptions. Useful for new model types
        that don't have a dedicated extractor yet.

        Args:
            data: Input data dictionary

        Returns:
            Dictionary of features extracted from data
        """
        features = {}
        for key, value in data.items():
            if isinstance(value, (int, float)):
                features[key] = value
            elif isinstance(value, str):
                features[key] = value
            elif isinstance(value, bool):
                features[key] = value
        return features

    def _extract_temporal_features(self, timestamp: datetime) -> Dict[str, Any]:
        """Extract time-based features.

        Args:
            timestamp: Transaction timestamp

        Returns:
            Dictionary of temporal features
        """
        # Ensure timezone awareness
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        return {
            "hour_of_day": timestamp.hour,
            "day_of_week": timestamp.weekday(),
            "day_of_month": timestamp.day,
            "month": timestamp.month,
            "year": timestamp.year,
            "is_weekend": timestamp.weekday() >= 5,
            "is_business_hours": 9 <= timestamp.hour <= 17,
            "is_night": timestamp.hour < 6 or timestamp.hour >= 22,
            "quarter": (timestamp.month - 1) // 3 + 1,
            "week_of_year": timestamp.isocalendar()[1],
            "unix_timestamp": int(timestamp.timestamp()),
        }

    def _extract_categorical_features(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract categorical features.

        Args:
            data: Input data dictionary

        Returns:
            Dictionary of categorical features
        """
        features = {}

        # Location features
        features["country"] = data.get("country", "unknown")
        features["state"] = data.get("state", "unknown")
        features["city"] = data.get("city", "unknown")
        features["zip_code"] = data.get("zip_code", "unknown")

        # Device features
        features["device_type"] = data.get("device_type", "unknown")
        features["os_type"] = data.get("os_type", "unknown")
        features["browser"] = data.get("browser", "unknown")

        # Channel features
        features["channel"] = data.get("channel", "unknown")
        features["source"] = data.get("source", "unknown")

        return features

    def _extract_numerical_features(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract numerical features.

        Args:
            data: Input data dictionary

        Returns:
            Dictionary of numerical features
        """
        features = {}

        # Risk scores
        features["risk_score"] = float(data.get("risk_score", 0.0))
        features["fraud_score"] = float(data.get("fraud_score", 0.0))
        features["credit_score"] = float(data.get("credit_score", 0.0))

        # Account features
        features["account_age_days"] = int(data.get("account_age_days", 0))
        features["transaction_count"] = int(data.get("transaction_count", 0))
        features["account_balance"] = float(data.get("account_balance", 0.0))

        # Geographic features
        features["latitude"] = float(data.get("latitude", 0.0))
        features["longitude"] = float(data.get("longitude", 0.0))

        return features

    def _compute_derived_features(self, features: Dict[str, Any]) -> Dict[str, Any]:
        """Compute derived features from extracted features.

        Args:
            features: Dictionary of extracted features

        Returns:
            Dictionary of derived features
        """
        derived = {}

        # Amount ratio features
        account_balance = features.get("account_balance", 0)
        amount = features.get("amount", 0)

        if account_balance > 0:
            derived["amount_to_balance_ratio"] = amount / account_balance
        else:
            derived["amount_to_balance_ratio"] = 0

        # Risk combinations
        risk_score = features.get("risk_score", 0)
        fraud_score = features.get("fraud_score", 0)
        derived["combined_risk_score"] = (risk_score + fraud_score) / 2

        # Time-based combinations
        hour = features.get("hour_of_day", 0)
        is_weekend = features.get("is_weekend", False)
        derived["is_unusual_time"] = (hour < 6 or hour > 22) and is_weekend

        # Transaction frequency features
        transaction_count = features.get("transaction_count", 0)
        account_age_days = features.get("account_age_days", 1)
        derived["avg_transactions_per_day"] = transaction_count / max(
            account_age_days, 1
        )

        return derived

    def _categorize_amount(self, amount: float) -> str:
        """Categorize transaction amount.

        Args:
            amount: Transaction amount

        Returns:
            Amount category string
        """
        if amount < 10:
            return "micro"
        elif amount < 100:
            return "small"
        elif amount < 1000:
            return "medium"
        elif amount < 10000:
            return "large"
        else:
            return "huge"

    def _validate_features(self, features: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and clean extracted features.

        Args:
            features: Dictionary of features to validate

        Returns:
            Dictionary of validated features
        """
        validated = {}

        for key, value in features.items():
            try:
                # Handle NaN and infinity values
                if isinstance(value, (int, float)):
                    if np.isnan(value) or np.isinf(value):
                        validated[key] = 0
                    else:
                        validated[key] = value
                elif isinstance(value, str):
                    # Clean string values
                    validated[key] = value.strip()[:100]  # Limit string length
                else:
                    validated[key] = value

            except Exception:
                # If validation fails, use default value
                validated[key] = 0 if isinstance(value, (int, float)) else "unknown"

        return validated


class AggregateFeatures(beam.DoFn):
    """Aggregate features over time windows.

    This transform computes windowed aggregations of features
    for time-series analysis and model training.
    """

    def __init__(self, aggregation_config: Optional[Dict[str, Any]] = None):
        """Initialize feature aggregation transform.

        Args:
            aggregation_config: Configuration for aggregations
        """
        self.aggregation_config = aggregation_config or {}
        self.logger = logger.bind(component="AggregateFeatures")

    def setup(self):
        """Setup method called once per worker."""
        self.logger.info("AggregateFeatures transform initialized")

    def process(
        self, element: Tuple[Any, Iterable[Dict[str, Any]]]
    ) -> Iterable[Dict[str, Any]]:
        """Aggregate features for a group of elements.

        Args:
            element: Tuple of (key, list of feature dictionaries)

        Yields:
            Dict[str, Any]: Aggregated features
        """
        try:
            key, features_list = element
            features_list = list(features_list)

            if not features_list:
                return

            # Extract numeric features for aggregation
            amounts = [f.get("amount", 0) for f in features_list]
            risk_scores = [f.get("risk_score", 0) for f in features_list]
            fraud_scores = [f.get("fraud_score", 0) for f in features_list]

            # Compute aggregations
            aggregated = {
                "user_id": key,
                "window_start": min(f.get("timestamp", "") for f in features_list),
                "window_end": max(f.get("timestamp", "") for f in features_list),
                "record_count": len(features_list),
                # Amount aggregations
                "total_amount": sum(amounts),
                "avg_amount": np.mean(amounts) if amounts else 0,
                "std_amount": np.std(amounts) if len(amounts) > 1 else 0,
                "min_amount": min(amounts) if amounts else 0,
                "max_amount": max(amounts) if amounts else 0,
                "median_amount": np.median(amounts) if amounts else 0,
                # Risk aggregations
                "avg_risk_score": np.mean(risk_scores) if risk_scores else 0,
                "max_risk_score": max(risk_scores) if risk_scores else 0,
                "avg_fraud_score": np.mean(fraud_scores) if fraud_scores else 0,
                "max_fraud_score": max(fraud_scores) if fraud_scores else 0,
                # Categorical aggregations
                "unique_merchants": len(
                    set(f.get("merchant_category", "") for f in features_list)
                ),
                "unique_channels": len(
                    set(f.get("channel", "") for f in features_list)
                ),
                "unique_payment_methods": len(
                    set(f.get("payment_method", "") for f in features_list)
                ),
                # Temporal aggregations
                "weekend_transactions": sum(
                    1 for f in features_list if f.get("is_weekend", False)
                ),
                "night_transactions": sum(
                    1 for f in features_list if f.get("is_night", False)
                ),
                "business_hours_transactions": sum(
                    1 for f in features_list if f.get("is_business_hours", False)
                ),
                # Computed ratios
                "high_amount_ratio": sum(
                    1 for f in features_list if f.get("is_high_amount", False)
                )
                / len(features_list),
                "unusual_time_ratio": sum(
                    1 for f in features_list if f.get("is_unusual_time", False)
                )
                / len(features_list),
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }

            yield aggregated

        except Exception as e:
            error_info = {
                "error": str(e),
                "key": str(key),
                "feature_count": (
                    len(features_list) if "features_list" in locals() else 0
                ),
                "transform": "AggregateFeatures",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            self.logger.error("Feature aggregation failed", error=str(e), key=str(key))

            yield TaggedOutput("errors", error_info)


class WriteToFeatureStore(beam.DoFn):
    """Write features to the Feature Store (Redis + PostgreSQL).

    Buffers elements internally and flushes in batches for efficiency.
    Uses FeatureStore.bulk_put_features() for batched Redis pipeline
    and PostgreSQL upserts.
    """

    def __init__(
        self,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        redis_password: Optional[str] = None,
        db_host: Optional[str] = None,
        db_port: Optional[int] = None,
        db_name: Optional[str] = None,
        feature_group: str = "transaction_features",
        entity_key_field: str = "user_id",
        ttl_seconds: int = 86400,
        write_batch_size: int = 100,
    ):
        """Initialize WriteToFeatureStore DoFn.

        Args:
            redis_host: Redis server host.
            redis_port: Redis server port.
            redis_password: Redis password (optional).
            db_host: PostgreSQL host (uses config default if None).
            db_port: PostgreSQL port (uses config default if None).
            db_name: PostgreSQL database name (uses config default if None).
            feature_group: Feature group name for storage.
            entity_key_field: Field name to extract entity_id from elements.
            ttl_seconds: TTL for cached features.
            write_batch_size: Number of elements to buffer before flushing.
        """
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_password = redis_password
        self.db_host = db_host
        self.db_port = db_port
        self.db_name = db_name
        self.feature_group = feature_group
        self.entity_key_field = entity_key_field
        self.ttl_seconds = ttl_seconds
        self.write_batch_size = write_batch_size
        self.logger = logger.bind(
            component="WriteToFeatureStore", feature_group=feature_group
        )

    def setup(self):
        """Initialize shared Redis connection pool, database, and FeatureStore."""
        import redis as redis_lib

        try:
            # Initialize database connection for PostgreSQL persistence
            from src.database.session import initialize_database

            initialize_database()

            pool = redis_lib.ConnectionPool(
                host=self.redis_host,
                port=self.redis_port,
                password=self.redis_password,
                max_connections=10,
                decode_responses=False,
            )
            redis_client = redis_lib.Redis(connection_pool=pool)

            from src.feature_store.store import FeatureStore

            self._feature_store = FeatureStore(redis_client=redis_client)
            self._buffer: list = []
            self.logger.info(
                "WriteToFeatureStore initialized",
                redis_host=self.redis_host,
            )
        except Exception as e:
            self.logger.error("Failed to initialize WriteToFeatureStore", error=str(e))
            raise

    def process(self, element: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
        """Buffer element and flush when batch size is reached."""
        try:
            entity_id = element.get(self.entity_key_field)
            if entity_id is None or entity_id == "unknown":
                yield TaggedOutput(
                    "dead_letter",
                    {
                        "error": f"Missing or unknown {self.entity_key_field}",
                        "element": str(element)[:500],
                        "transform": "WriteToFeatureStore",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
                return

            # Exclude metadata fields from stored features
            exclude_fields = {
                "message_id",
                "timestamp",
                "processed_at",
                self.entity_key_field,
            }
            features = {k: v for k, v in element.items() if k not in exclude_fields}

            self._buffer.append((str(entity_id), features))

            if len(self._buffer) >= self.write_batch_size:
                self._flush_batch()

        except Exception as e:
            self.logger.error("WriteToFeatureStore process error", error=str(e))
            yield TaggedOutput(
                "dead_letter",
                {
                    "error": str(e),
                    "element": str(element)[:500],
                    "transform": "WriteToFeatureStore",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

    def _flush_batch(self) -> None:
        """Flush buffered elements to the Feature Store."""
        if not self._buffer:
            return

        try:
            self._feature_store.bulk_put_features(
                entities=self._buffer,
                feature_group=self.feature_group,
                ttl_seconds=self.ttl_seconds,
            )
            self.logger.debug(
                "Flushed batch to feature store",
                batch_size=len(self._buffer),
            )
        except Exception as e:
            self.logger.error(
                "Failed to flush batch to feature store",
                batch_size=len(self._buffer),
                error=str(e),
            )
        finally:
            self._buffer.clear()

    def finish_bundle(self):
        """Flush remaining buffered elements at end of bundle."""
        self._flush_batch()

    def teardown(self):
        """Clean up connections."""
        try:
            if hasattr(self, "_feature_store") and self._feature_store:
                self._feature_store.redis_client.close()
        except Exception as e:
            # Do not raise during teardown, but log the failure for observability.
            self.logger.error(
                "Failed to close feature store Redis client during teardown",
                error=str(e),
            )


class ValidateFeatures(beam.DoFn):
    """Validate feature quality and completeness.

    This transform ensures that features meet quality requirements
    before being used for model training or inference.
    """

    def __init__(self, validation_config: Optional[Dict[str, Any]] = None):
        """Initialize feature validation transform.

        Args:
            validation_config: Configuration for validation rules
        """
        self.validation_config = validation_config or {}
        self.required_fields = self.validation_config.get("required_fields", [])
        self.numeric_ranges = self.validation_config.get("numeric_ranges", {})
        self.categorical_values = self.validation_config.get("categorical_values", {})

    def process(self, element: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
        """Validate features.

        Args:
            element: Feature dictionary to validate

        Yields:
            Dict[str, Any]: Validated features or error information
        """
        try:
            validation_results = {
                "is_valid": True,
                "validation_errors": [],
                "features": element.copy(),
            }

            # Check required fields
            for field in self.required_fields:
                if field not in element or element[field] is None:
                    validation_results["is_valid"] = False
                    validation_results["validation_errors"].append(
                        f"Missing required field: {field}"
                    )

            # Validate numeric ranges
            for field, (min_val, max_val) in self.numeric_ranges.items():
                if field in element:
                    value = element[field]
                    if isinstance(value, (int, float)):
                        if value < min_val or value > max_val:
                            validation_results["is_valid"] = False
                            validation_results["validation_errors"].append(
                                f"Field {field} value {value} outside range [{min_val}, {max_val}]"
                            )

            # Validate categorical values
            for field, allowed_values in self.categorical_values.items():
                if field in element:
                    value = element[field]
                    if value not in allowed_values:
                        validation_results["is_valid"] = False
                        validation_results["validation_errors"].append(
                            f"Field {field} value '{value}' not in allowed values: {allowed_values}"
                        )

            if validation_results["is_valid"]:
                yield element
            else:
                yield TaggedOutput("invalid", validation_results)

        except Exception as e:
            error_info = {
                "error": str(e),
                "element": str(element)[:1000],
                "transform": "ValidateFeatures",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            yield TaggedOutput("errors", error_info)
