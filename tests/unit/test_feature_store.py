"""Unit tests for feature store functionality."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from src.feature_store.store import FeatureStore
from src.feature_store.client import FeatureStoreClient
from src.feature_store.transforms import (
    NumericTransform, CategoricalTransform, DateTimeTransform,
    BooleanTransform, TextTransform
)


class TestFeatureStore:
    """Test FeatureStore class."""

    def test_put_and_get_features(self, mock_redis, test_config):
        """Test storing and retrieving features."""
        store = FeatureStore(redis_client=mock_redis)

        # Test data
        entity_id = "user_123"
        feature_group = "user_features"
        features = {
            "age": 25,
            "city": "New York",
            "is_premium": True
        }

        # Store features
        store.put_features(entity_id, feature_group, features)

        # Retrieve features
        retrieved = store.get_features(entity_id, feature_group)

        assert retrieved == features

    def test_get_specific_features(self, mock_redis, test_config):
        """Test retrieving specific features by name."""
        store = FeatureStore(redis_client=mock_redis)

        entity_id = "user_123"
        feature_group = "user_features"
        features = {
            "age": 25,
            "city": "New York",
            "is_premium": True,
            "score": 0.8
        }

        store.put_features(entity_id, feature_group, features)

        # Retrieve specific features
        specific_features = store.get_features(
            entity_id, feature_group, feature_names=["age", "city"]
        )

        expected = {"age": 25, "city": "New York"}
        assert specific_features == expected

    def test_get_batch_features(self, mock_redis, test_config):
        """Test batch feature retrieval."""
        store = FeatureStore(redis_client=mock_redis)

        feature_group = "user_features"
        entities_features = {
            "user_1": {"age": 25, "city": "New York"},
            "user_2": {"age": 30, "city": "Boston"},
            "user_3": {"age": 35, "city": "Chicago"}
        }

        # Store features for multiple entities
        for entity_id, features in entities_features.items():
            store.put_features(entity_id, feature_group, features)

        # Retrieve batch features
        batch_result = store.get_batch_features(
            list(entities_features.keys()), feature_group
        )

        assert batch_result == entities_features

    def test_delete_features(self, mock_redis, test_config):
        """Test feature deletion."""
        store = FeatureStore(redis_client=mock_redis)

        entity_id = "user_123"
        feature_group = "user_features"
        features = {"age": 25, "city": "New York"}

        # Store and then delete
        store.put_features(entity_id, feature_group, features)
        store.delete_features(entity_id, feature_group)

        # Should not find features in cache
        retrieved = store.get_features(entity_id, feature_group)
        assert retrieved == {}

    def test_ttl_functionality(self, mock_redis, test_config):
        """Test TTL functionality."""
        store = FeatureStore(redis_client=mock_redis)

        entity_id = "user_123"
        feature_group = "user_features"
        features = {"age": 25}

        # Store with short TTL
        store.put_features(entity_id, feature_group, features, ttl_seconds=1)

        # Should be able to retrieve immediately
        retrieved = store.get_features(entity_id, feature_group)
        assert retrieved == features

        # Mock Redis expiration
        mock_redis.delete(store._build_cache_key(entity_id, feature_group))

        # Should not find in cache after expiration
        retrieved = store.get_features(entity_id, feature_group)
        assert retrieved == {}

    def test_health_status(self, mock_redis, test_config):
        """Test health status reporting."""
        store = FeatureStore(redis_client=mock_redis)

        health = store.get_health_status()

        assert isinstance(health, dict)
        assert "redis_connected" in health
        assert "database_connected" in health
        assert "timestamp" in health


class TestFeatureStoreClient:
    """Test FeatureStoreClient class."""

    def test_feature_transformations(self, feature_store_client, sample_features):
        """Test feature transformations."""
        client = feature_store_client

        # Test storing with transforms
        entity_id = "user_123"
        feature_group = "test_features"

        client.put_features(
            entity_id, feature_group, sample_features, apply_transforms=True
        )

        # Retrieve and verify transforms were applied
        retrieved = client.get_features(
            entity_id, feature_group, apply_transforms=False
        )

        # Amount should be within bounds
        assert 0 <= retrieved["amount"] <= 10000
        # Merchant category should be valid
        assert retrieved["merchant_category"] in [
            "electronics", "grocery", "gas", "restaurant", "retail", "other"
        ]

    def test_feature_vector_creation(self, feature_store_client):
        """Test feature vector creation."""
        client = feature_store_client

        entity_id = "user_123"

        # Store features in different groups
        client.put_features(entity_id, "demographics", {"age": 25, "income": 50000})
        client.put_features(entity_id, "behavior", {"clicks": 10, "purchases": 2})

        # Create feature vector
        feature_schema = {
            "demographics": ["age", "income"],
            "behavior": ["clicks", "purchases"]
        }

        feature_vector = client.create_feature_vector(
            entity_id, ["demographics", "behavior"], feature_schema
        )

        expected_keys = {
            "demographics_age", "demographics_income",
            "behavior_clicks", "behavior_purchases"
        }
        assert set(feature_vector.keys()) == expected_keys

    def test_batch_feature_vectors(self, feature_store_client):
        """Test batch feature vector creation."""
        client = feature_store_client

        entity_ids = ["user_1", "user_2"]
        feature_group = "test_features"

        # Store features for multiple entities
        for i, entity_id in enumerate(entity_ids):
            client.put_features(entity_id, feature_group, {"score": i * 10})

        # Create batch feature vectors
        feature_schema = {feature_group: ["score"]}
        batch_vectors = client.create_batch_feature_vectors(
            entity_ids, [feature_group], feature_schema
        )

        assert len(batch_vectors) == 2
        assert f"{feature_group}_score" in batch_vectors["user_1"]
        assert f"{feature_group}_score" in batch_vectors["user_2"]

    def test_missing_value_handling(self, feature_store_client):
        """Test missing value handling in feature vectors."""
        client = feature_store_client

        entity_id = "user_123"
        feature_group = "test_features"

        # Store incomplete features
        client.put_features(entity_id, feature_group, {"existing_feature": 1})

        # Request vector with missing features
        feature_schema = {feature_group: ["existing_feature", "missing_feature"]}
        feature_vector = client.create_feature_vector(
            entity_id, [feature_group], feature_schema, fill_missing=True
        )

        assert f"{feature_group}_existing_feature" in feature_vector
        assert f"{feature_group}_missing_feature" in feature_vector
        assert feature_vector[f"{feature_group}_missing_feature"] == 0.0


class TestFeatureTransforms:
    """Test feature transformation classes."""

    def test_numeric_transform(self):
        """Test numeric transformation."""
        transform = NumericTransform(
            min_value=0, max_value=100, normalize=True, clip_outliers=True
        )

        # Test normal value
        assert transform.transform(50) == 0.5

        # Test clipping
        assert transform.transform(-10) == 0.0
        assert transform.transform(150) == 1.0

        # Test missing value handling
        assert transform.transform(None) == 0.0
        assert transform.transform("") == 0.0

    def test_categorical_transform(self):
        """Test categorical transformation."""
        valid_categories = ["red", "green", "blue"]
        transform = CategoricalTransform(
            valid_categories=valid_categories,
            encode_as_numeric=True,
            case_sensitive=False
        )

        # Test valid categories
        assert transform.transform("red") == 0
        assert transform.transform("GREEN") == 1  # Case insensitive

        # Test invalid category
        assert transform.transform("yellow") == len(valid_categories)

        # Test missing values
        assert transform.transform(None) == len(valid_categories)

    def test_datetime_transform(self):
        """Test datetime transformation."""
        transform = DateTimeTransform(output_format="components")

        # Test datetime object
        test_dt = datetime(2023, 6, 15, 14, 30, 0)
        result = transform.transform(test_dt)

        assert isinstance(result, dict)
        assert result["year"] == 2023
        assert result["month"] == 6
        assert result["day"] == 15
        assert result["hour"] == 14

        # Test string parsing
        result = transform.transform("2023-06-15 14:30:00")
        assert result["year"] == 2023

        # Test timestamp format
        timestamp_transform = DateTimeTransform(output_format="timestamp")
        timestamp = timestamp_transform.transform(test_dt)
        assert isinstance(timestamp, float)

    def test_boolean_transform(self):
        """Test boolean transformation."""
        transform = BooleanTransform(output_as_numeric=True)

        # Test various true values
        assert transform.transform(True) == 1
        assert transform.transform("true") == 1
        assert transform.transform("yes") == 1
        assert transform.transform(1) == 1

        # Test various false values
        assert transform.transform(False) == 0
        assert transform.transform("false") == 0
        assert transform.transform("no") == 0
        assert transform.transform(0) == 0

        # Test missing values
        assert transform.transform(None) == 0

    def test_text_transform(self):
        """Test text transformation."""
        transform = TextTransform(
            max_length=10,
            lowercase=True,
            strip_whitespace=True,
            remove_special_chars=True
        )

        # Test normal text
        result = transform.transform("  Hello World!  ")
        assert result == "hello worl"  # Lowercased, stripped, special chars removed, truncated

        # Test missing values
        assert transform.transform(None) == ""
        assert transform.transform("") == ""

    def test_transform_error_handling(self):
        """Test transform error handling."""
        transform = NumericTransform()

        # Test invalid numeric value
        result = transform.transform("not_a_number")
        assert result == 0.0  # Should use default value

        # Test with fill_missing=False
        transform_no_fill = NumericTransform(fill_missing=False)
        result = transform_no_fill.transform(None)
        assert result is None