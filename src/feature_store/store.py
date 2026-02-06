"""Feature store implementation for real-time feature serving."""

import pickle
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import redis
import structlog

from ..database.models import FeatureStore as FeatureStoreModel
from ..database.session import get_session
from ..utils.config import get_config

logger = structlog.get_logger()


class FeatureStore:
    """High-performance feature store with Redis caching and PostgreSQL persistence."""

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        """Initialize feature store.

        Args:
            redis_client: Optional Redis client. If None, will create from config.
        """
        self.config = get_config()

        if redis_client is None:
            redis_config = self.config.redis
            self.redis_client = redis.Redis(
                host=redis_config.host,
                port=redis_config.port,
                password=redis_config.password,
                db=redis_config.db,
                socket_timeout=redis_config.socket_timeout,
                socket_connect_timeout=redis_config.socket_connect_timeout,
                max_connections=redis_config.max_connections,
                retry_on_timeout=redis_config.retry_on_timeout,
                decode_responses=False,  # We'll handle encoding/decoding manually
            )
        else:
            self.redis_client = redis_client

        self.logger = logger.bind(component="FeatureStore")
        self.default_ttl = self.config.feature_store_ttl

    def put_features(
        self,
        entity_id: str,
        feature_group: str,
        features: Dict[str, Any],
        event_timestamp: Optional[datetime] = None,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """Store features for an entity.

        Args:
            entity_id: Unique identifier for the entity
            feature_group: Feature group name
            features: Dictionary of feature name -> value
            event_timestamp: Timestamp of the event (defaults to now)
            ttl_seconds: TTL for cached features (defaults to config value)
        """
        if event_timestamp is None:
            event_timestamp = datetime.now(timezone.utc)

        if ttl_seconds is None:
            ttl_seconds = self.default_ttl

        try:
            # Store in Redis for fast access
            cache_key = self._build_cache_key(entity_id, feature_group)
            cached_data = {
                "features": features,
                "event_timestamp": event_timestamp.isoformat(),
                "feature_group": feature_group,
                "entity_id": entity_id,
            }

            # Use pickle for efficient serialization
            serialized_data = pickle.dumps(cached_data)
            self.redis_client.setex(cache_key, ttl_seconds, serialized_data)

            # Store in database for persistence
            self._persist_features(
                entity_id, feature_group, features, event_timestamp, ttl_seconds
            )

            self.logger.debug(
                "Features stored",
                entity_id=entity_id,
                feature_group=feature_group,
                feature_count=len(features),
                ttl_seconds=ttl_seconds,
            )

        except Exception as e:
            self.logger.error(
                "Failed to store features",
                entity_id=entity_id,
                feature_group=feature_group,
                error=str(e),
            )
            raise

    def get_features(
        self,
        entity_id: str,
        feature_group: str,
        feature_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Retrieve features for an entity.

        Args:
            entity_id: Unique identifier for the entity
            feature_group: Feature group name
            feature_names: Optional list of specific features to retrieve

        Returns:
            Dictionary of feature name -> value
        """
        try:
            # Try Redis cache first
            cache_key = self._build_cache_key(entity_id, feature_group)

            try:
                cached_data = self.redis_client.get(cache_key)

                if cached_data:
                    try:
                        data = pickle.loads(cached_data)
                        features = data["features"]

                        # Filter specific feature names if requested
                        if feature_names:
                            features = {
                                name: features[name]
                                for name in feature_names
                                if name in features
                            }

                        self.logger.debug(
                            "Features retrieved from cache",
                            entity_id=entity_id,
                            feature_group=feature_group,
                            feature_count=len(features),
                        )

                        return features

                    except (pickle.PickleError, KeyError) as e:
                        self.logger.warning(
                            "Failed to deserialize cached features, falling back to database",
                            entity_id=entity_id,
                            feature_group=feature_group,
                            error=str(e),
                        )

            except Exception as e:
                self.logger.warning(
                    "Redis cache unavailable, falling back to database",
                    entity_id=entity_id,
                    feature_group=feature_group,
                    error=str(e),
                )

            # Fallback to database
            return self._get_features_from_db(entity_id, feature_group, feature_names)

        except Exception as e:
            self.logger.error(
                "Failed to retrieve features",
                entity_id=entity_id,
                feature_group=feature_group,
                error=str(e),
            )
            raise

    def get_batch_features(
        self,
        entity_ids: List[str],
        feature_group: str,
        feature_names: Optional[List[str]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Retrieve features for multiple entities efficiently.

        Args:
            entity_ids: List of entity identifiers
            feature_group: Feature group name
            feature_names: Optional list of specific features to retrieve

        Returns:
            Dictionary mapping entity_id -> feature dictionary
        """
        try:
            result = {}

            # Batch Redis operations
            cache_keys = [
                self._build_cache_key(entity_id, feature_group)
                for entity_id in entity_ids
            ]
            cached_values = self.redis_client.mget(cache_keys)

            # Process cached results and identify missing entities
            missing_entities = []
            for i, (entity_id, cached_data) in enumerate(
                zip(entity_ids, cached_values)
            ):
                if cached_data:
                    try:
                        data = pickle.loads(cached_data)
                        features = data["features"]

                        if feature_names:
                            features = {
                                name: features[name]
                                for name in feature_names
                                if name in features
                            }

                        result[entity_id] = features
                    except (pickle.PickleError, KeyError):
                        missing_entities.append(entity_id)
                else:
                    missing_entities.append(entity_id)

            # Fetch missing entities from database
            if missing_entities:
                db_features = self._get_batch_features_from_db(
                    missing_entities, feature_group, feature_names
                )
                result.update(db_features)

                # Cache the database results
                for entity_id, features in db_features.items():
                    cache_key = self._build_cache_key(entity_id, feature_group)
                    cached_data = {
                        "features": features,
                        "event_timestamp": datetime.now(timezone.utc).isoformat(),
                        "feature_group": feature_group,
                        "entity_id": entity_id,
                    }
                    serialized_data = pickle.dumps(cached_data)
                    self.redis_client.setex(
                        cache_key, self.default_ttl, serialized_data
                    )

            self.logger.debug(
                "Batch features retrieved",
                feature_group=feature_group,
                total_entities=len(entity_ids),
                cached_entities=len(entity_ids) - len(missing_entities),
                db_entities=len(missing_entities),
            )

            return result

        except Exception as e:
            self.logger.error(
                "Failed to retrieve batch features",
                feature_group=feature_group,
                entity_count=len(entity_ids),
                error=str(e),
            )
            raise

    def delete_features(self, entity_id: str, feature_group: str) -> None:
        """Delete all features for an entity in a feature group.

        Args:
            entity_id: Unique identifier for the entity
            feature_group: Feature group name
        """
        try:
            # Delete from cache
            cache_key = self._build_cache_key(entity_id, feature_group)
            self.redis_client.delete(cache_key)

            # Mark as inactive in database (soft delete)
            with get_session() as session:
                session.query(FeatureStoreModel).filter(
                    FeatureStoreModel.entity_id == entity_id,
                    FeatureStoreModel.feature_group == feature_group,
                ).update({FeatureStoreModel.is_active: False})

            self.logger.info(
                "Features deleted", entity_id=entity_id, feature_group=feature_group
            )

        except Exception as e:
            self.logger.error(
                "Failed to delete features",
                entity_id=entity_id,
                feature_group=feature_group,
                error=str(e),
            )
            raise

    def cleanup_expired_features(self) -> int:
        """Clean up expired features from the database.

        Returns:
            Number of features cleaned up
        """
        try:
            current_time = datetime.now(timezone.utc)

            with get_session() as session:
                # Mark expired features as inactive
                expired_count = (
                    session.query(FeatureStoreModel)
                    .filter(
                        FeatureStoreModel.ttl_timestamp <= current_time,
                        FeatureStoreModel.is_active is True,
                    )
                    .update({FeatureStoreModel.is_active: False})
                )

            self.logger.info("Expired features cleaned up", count=expired_count)

            return expired_count

        except Exception as e:
            self.logger.error("Failed to cleanup expired features", error=str(e))
            raise

    def get_feature_groups(self) -> List[str]:
        """Get list of all feature groups.

        Returns:
            List of feature group names
        """
        try:
            with get_session() as session:
                feature_groups = (
                    session.query(FeatureStoreModel.feature_group).distinct().all()
                )
                return [fg[0] for fg in feature_groups]

        except Exception as e:
            self.logger.error("Failed to retrieve feature groups", error=str(e))
            raise

    def get_health_status(self) -> Dict[str, Any]:
        """Get health status of the feature store.

        Returns:
            Dictionary with health information
        """
        try:
            status = {
                "redis_connected": False,
                "database_connected": False,
                "cache_info": {},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            # Check Redis connectivity
            try:
                self.redis_client.ping()
                status["redis_connected"] = True
                status["cache_info"] = self.redis_client.info("memory")
            except Exception as e:
                self.logger.warning("Redis health check failed", error=str(e))

            # Check database connectivity
            try:
                with get_session() as session:
                    session.execute("SELECT 1")
                status["database_connected"] = True
            except Exception as e:
                self.logger.warning("Database health check failed", error=str(e))

            return status

        except Exception as e:
            self.logger.error("Failed to get health status", error=str(e))
            raise

    def _build_cache_key(self, entity_id: str, feature_group: str) -> str:
        """Build Redis cache key.

        Args:
            entity_id: Entity identifier
            feature_group: Feature group name

        Returns:
            Cache key string
        """
        return f"features:{feature_group}:{entity_id}"

    def _persist_features(
        self,
        entity_id: str,
        feature_group: str,
        features: Dict[str, Any],
        event_timestamp: datetime,
        ttl_seconds: int,
    ) -> None:
        """Persist features to database.

        Args:
            entity_id: Entity identifier
            feature_group: Feature group name
            features: Feature dictionary
            event_timestamp: Event timestamp
            ttl_seconds: TTL in seconds
        """
        ttl_timestamp = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

        with get_session() as session:
            for feature_name, feature_value in features.items():
                # Determine data type
                data_type = self._determine_data_type(feature_value)

                # Create or update feature record
                feature_record = FeatureStoreModel(
                    entity_id=entity_id,
                    feature_group=feature_group,
                    feature_name=feature_name,
                    feature_value=feature_value,
                    data_type=data_type,
                    event_timestamp=event_timestamp,
                    ttl_timestamp=ttl_timestamp,
                )

                session.merge(feature_record)

    def _get_features_from_db(
        self,
        entity_id: str,
        feature_group: str,
        feature_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Retrieve features from database.

        Args:
            entity_id: Entity identifier
            feature_group: Feature group name
            feature_names: Optional list of specific features

        Returns:
            Feature dictionary
        """
        with get_session() as session:
            query = session.query(FeatureStoreModel).filter(
                FeatureStoreModel.entity_id == entity_id,
                FeatureStoreModel.feature_group == feature_group,
                FeatureStoreModel.is_active is True,
            )

            if feature_names:
                query = query.filter(FeatureStoreModel.feature_name.in_(feature_names))

            features = {}
            for record in query.all():
                features[record.feature_name] = record.feature_value

            return features

    def _get_batch_features_from_db(
        self,
        entity_ids: List[str],
        feature_group: str,
        feature_names: Optional[List[str]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Retrieve batch features from database.

        Args:
            entity_ids: List of entity identifiers
            feature_group: Feature group name
            feature_names: Optional list of specific features

        Returns:
            Dictionary mapping entity_id -> feature dictionary
        """
        with get_session() as session:
            query = session.query(FeatureStoreModel).filter(
                FeatureStoreModel.entity_id.in_(entity_ids),
                FeatureStoreModel.feature_group == feature_group,
                FeatureStoreModel.is_active is True,
            )

            if feature_names:
                query = query.filter(FeatureStoreModel.feature_name.in_(feature_names))

            result = {}
            for record in query.all():
                entity_id = record.entity_id
                if entity_id not in result:
                    result[entity_id] = {}
                result[entity_id][record.feature_name] = record.feature_value

            return result

    def _determine_data_type(self, value: Any) -> str:
        """Determine data type for a feature value.

        Args:
            value: Feature value

        Returns:
            Data type string
        """
        if isinstance(value, (int, float)):
            return "numeric"
        elif isinstance(value, bool):
            return "boolean"
        elif isinstance(value, str):
            return "categorical"
        elif isinstance(value, datetime):
            return "datetime"
        else:
            return "text"
