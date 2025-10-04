"""Integration tests for feature store with Redis and database."""

import pytest
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from src.feature_store.store import FeatureStore
from src.feature_store.client import FeatureStoreClient
from src.database.models import FeatureStore as FeatureStoreModel


class TestFeatureStoreIntegration:
    """Test feature store integration with Redis and PostgreSQL."""

    @pytest.fixture
    def feature_store(self, mock_redis, test_database):
        """Create feature store with test dependencies."""
        # Initialize database tables
        test_database.create_tables()

        # Set the global database manager
        import src.database.session as session_module
        session_module._db_manager = test_database

        store = FeatureStore(redis_client=mock_redis)
        return store

    @pytest.fixture
    def feature_client(self, feature_store):
        """Create feature store client."""
        client = FeatureStoreClient(feature_store=feature_store)
        client.setup_common_transforms()
        return client

    def test_feature_persistence_flow(self, feature_store, db_session):
        """Test complete feature persistence flow."""
        entity_id = "user_123"
        feature_group = "demographics"
        features = {
            "age": 25,
            "income": 50000,
            "city": "New York"
        }

        # Store features
        feature_store.put_features(entity_id, feature_group, features)

        # Verify in Redis cache
        retrieved_from_cache = feature_store.get_features(entity_id, feature_group)
        assert retrieved_from_cache == features

        # Verify in database
        db_features = db_session.query(FeatureStoreModel).filter_by(
            entity_id=entity_id,
            feature_group=feature_group
        ).all()

        assert len(db_features) == 3
        feature_dict = {f.feature_name: f.feature_value for f in db_features}
        assert feature_dict == features

    def test_cache_miss_fallback_to_database(self, feature_store, mock_redis, db_session):
        """Test fallback to database when cache miss occurs."""
        entity_id = "user_456"
        feature_group = "behavior"
        features = {"clicks": 10, "purchases": 2}

        # Store features first
        feature_store.put_features(entity_id, feature_group, features)

        # Clear Redis cache to simulate cache miss
        cache_key = feature_store._build_cache_key(entity_id, feature_group)
        mock_redis.delete(cache_key)

        # Retrieve features - should fallback to database
        retrieved = feature_store.get_features(entity_id, feature_group)
        assert retrieved == features

    def test_batch_operations_performance(self, feature_store):
        """Test batch operations for performance."""
        feature_group = "test_batch"
        entity_count = 100

        # Prepare batch data
        batch_data = {}
        for i in range(entity_count):
            entity_id = f"user_{i}"
            features = {
                "score": i * 10,
                "level": i % 5,
                "active": i % 2 == 0
            }
            batch_data[entity_id] = features

        # Store features individually (simulating real-time ingestion)
        for entity_id, features in batch_data.items():
            feature_store.put_features(entity_id, feature_group, features)

        # Retrieve in batch
        entity_ids = list(batch_data.keys())
        retrieved_batch = feature_store.get_batch_features(entity_ids, feature_group)

        # Verify all data was retrieved correctly
        assert len(retrieved_batch) == entity_count
        for entity_id, expected_features in batch_data.items():
            assert retrieved_batch[entity_id] == expected_features

    def test_feature_ttl_expiration(self, feature_store, mock_redis):
        """Test feature TTL and expiration handling."""
        entity_id = "user_ttl"
        feature_group = "temp_features"
        features = {"temp_score": 100}

        # Store with short TTL
        feature_store.put_features(entity_id, feature_group, features, ttl_seconds=1)

        # Should be retrievable immediately
        retrieved = feature_store.get_features(entity_id, feature_group)
        assert retrieved == features

        # Simulate TTL expiration by deleting from Redis
        cache_key = feature_store._build_cache_key(entity_id, feature_group)
        mock_redis.delete(cache_key)

        # Should still be in database but not in cache
        # (In real scenario, database cleanup would happen via scheduled job)
        retrieved = feature_store.get_features(entity_id, feature_group)
        assert retrieved == features

    def test_feature_versioning(self, feature_store):
        """Test feature versioning and updates."""
        entity_id = "user_versioning"
        feature_group = "profile"

        # Store initial version
        initial_features = {"name": "John", "age": 25}
        feature_store.put_features(entity_id, feature_group, initial_features)

        # Update with new version
        updated_features = {"name": "John Doe", "age": 26, "city": "Boston"}
        feature_store.put_features(entity_id, feature_group, updated_features)

        # Should retrieve latest version
        retrieved = feature_store.get_features(entity_id, feature_group)
        assert retrieved == updated_features

    def test_partial_feature_retrieval(self, feature_store):
        """Test retrieving specific features by name."""
        entity_id = "user_partial"
        feature_group = "complete_profile"
        all_features = {
            "name": "Alice",
            "age": 30,
            "email": "alice@example.com",
            "phone": "123-456-7890",
            "address": "123 Main St"
        }

        feature_store.put_features(entity_id, feature_group, all_features)

        # Retrieve only specific features
        requested_features = ["name", "email"]
        partial_features = feature_store.get_features(
            entity_id, feature_group, feature_names=requested_features
        )

        expected = {"name": "Alice", "email": "alice@example.com"}
        assert partial_features == expected

    def test_error_handling_and_recovery(self, feature_store, mock_redis):
        """Test error handling and recovery scenarios."""
        entity_id = "user_error"
        feature_group = "error_test"
        features = {"test_feature": 123}

        # Store features successfully
        feature_store.put_features(entity_id, feature_group, features)

        # Simulate Redis connection error
        with patch.object(mock_redis, 'get', side_effect=Exception("Redis connection failed")):
            # Should still work via database fallback
            retrieved = feature_store.get_features(entity_id, feature_group)
            assert retrieved == features

    def test_data_type_handling(self, feature_store):
        """Test handling of different data types."""
        entity_id = "user_datatypes"
        feature_group = "mixed_types"
        mixed_features = {
            "integer_feature": 42,
            "float_feature": 3.14,
            "string_feature": "hello",
            "boolean_feature": True,
            "list_feature": [1, 2, 3],
            "dict_feature": {"nested": "value"}
        }

        feature_store.put_features(entity_id, feature_group, mixed_features)
        retrieved = feature_store.get_features(entity_id, feature_group)

        assert retrieved == mixed_features

    def test_feature_cleanup(self, feature_store, db_session):
        """Test feature cleanup functionality."""
        entity_id = "user_cleanup"
        feature_group = "cleanup_test"
        features = {"cleanup_feature": 100}

        # Store features with past TTL
        past_time = datetime.now(timezone.utc) - timedelta(hours=1)
        feature_store.put_features(entity_id, feature_group, features, ttl_seconds=1)

        # Manually update TTL timestamp to past for testing
        db_session.query(FeatureStoreModel).filter_by(
            entity_id=entity_id,
            feature_group=feature_group
        ).update({FeatureStoreModel.ttl_timestamp: past_time})
        db_session.commit()

        # Run cleanup
        cleaned_count = feature_store.cleanup_expired_features()
        assert cleaned_count > 0

        # Verify features are marked as inactive
        inactive_features = db_session.query(FeatureStoreModel).filter_by(
            entity_id=entity_id,
            feature_group=feature_group,
            is_active=False
        ).all()
        assert len(inactive_features) > 0


class TestFeatureStoreClientIntegration:
    """Test feature store client integration."""

    def test_end_to_end_feature_pipeline(self, feature_store_client, sample_features):
        """Test complete feature pipeline from ingestion to vector creation."""
        entity_id = "user_pipeline"

        # Store features in different groups
        demographics = {
            "age": sample_features["user_age"],
            "income": 50000
        }

        behavior = {
            "clicks": sample_features.get("transaction_count_24h", 5),
            "purchases": 2
        }

        transaction = {
            "amount": sample_features["amount"],
            "merchant_category": sample_features["merchant_category"]
        }

        # Store features with transformations
        feature_store_client.put_features(entity_id, "demographics", demographics, apply_transforms=True)
        feature_store_client.put_features(entity_id, "behavior", behavior, apply_transforms=True)
        feature_store_client.put_features(entity_id, "transaction", transaction, apply_transforms=True)

        # Create feature vector
        feature_schema = {
            "demographics": ["age", "income"],
            "behavior": ["clicks", "purchases"],
            "transaction": ["amount", "merchant_category"]
        }

        feature_vector = feature_store_client.create_feature_vector(
            entity_id,
            ["demographics", "behavior", "transaction"],
            feature_schema,
            apply_transforms=True,
            fill_missing=True
        )

        # Verify feature vector structure
        expected_keys = {
            "demographics_age", "demographics_income",
            "behavior_clicks", "behavior_purchases",
            "transaction_amount", "transaction_merchant_category"
        }
        assert set(feature_vector.keys()) == expected_keys

        # Verify transformations were applied
        assert isinstance(feature_vector["demographics_age"], (int, float))
        assert isinstance(feature_vector["transaction_amount"], (int, float))

    def test_batch_feature_vector_creation(self, feature_store_client):
        """Test batch feature vector creation."""
        entity_ids = [f"user_{i}" for i in range(5)]
        feature_group = "batch_test"

        # Store features for all entities
        for i, entity_id in enumerate(entity_ids):
            features = {
                "score": i * 10,
                "category": f"cat_{i % 3}",
                "active": i % 2 == 0
            }
            feature_store_client.put_features(entity_id, feature_group, features)

        # Create batch feature vectors
        feature_schema = {feature_group: ["score", "category", "active"]}
        batch_vectors = feature_store_client.create_batch_feature_vectors(
            entity_ids,
            [feature_group],
            feature_schema,
            fill_missing=True
        )

        # Verify all entities have feature vectors
        assert len(batch_vectors) == len(entity_ids)
        for entity_id in entity_ids:
            assert entity_id in batch_vectors
            vector = batch_vectors[entity_id]
            assert f"{feature_group}_score" in vector
            assert f"{feature_group}_category" in vector
            assert f"{feature_group}_active" in vector

    def test_feature_statistics_collection(self, feature_store_client, db_session):
        """Test feature statistics collection."""
        feature_group = "stats_test"

        # Create diverse feature data
        entities_data = [
            ("user_1", {"age": 25, "income": 40000, "category": "A"}),
            ("user_2", {"age": 30, "income": 60000, "category": "B"}),
            ("user_3", {"age": 35, "income": 80000, "category": "A"}),
            ("user_4", {"age": 28, "income": 50000, "category": "C"}),
        ]

        for entity_id, features in entities_data:
            feature_store_client.put_features(entity_id, feature_group, features)

        # Get feature statistics
        stats = feature_store_client.get_feature_statistics(feature_group)

        assert stats["feature_group"] == feature_group
        assert stats["unique_entities"] == 4
        assert stats["total_features"] == 12  # 4 entities * 3 features each

        # Check feature counts
        assert stats["feature_counts"]["age"] == 4
        assert stats["feature_counts"]["income"] == 4
        assert stats["feature_counts"]["category"] == 4

    def test_transformation_error_handling(self, feature_store_client):
        """Test transformation error handling."""
        entity_id = "user_transform_error"
        feature_group = "error_transforms"

        # Features that might cause transformation errors
        problematic_features = {
            "amount": "not_a_number",  # Should be numeric
            "merchant_category": "unknown_category",  # Invalid category
            "malformed_data": {"nested": "object"}  # Unexpected format
        }

        # Should handle errors gracefully
        feature_store_client.put_features(
            entity_id,
            feature_group,
            problematic_features,
            apply_transforms=True
        )

        # Retrieve and verify error handling
        retrieved = feature_store_client.get_features(
            entity_id,
            feature_group,
            apply_transforms=True
        )

        # Transformations should have applied defaults for invalid data
        assert "amount" in retrieved
        assert "merchant_category" in retrieved