"""Feature store implementation for real-time feature serving."""

import pickle
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import redis
import structlog
from sqlalchemy import text

from ..database.models import FeatureStore as FeatureStoreModel
from ..database.session import get_session
from ..utils.config import get_config

logger = structlog.get_logger()

# Optional Prometheus metrics
_prometheus_metrics = None


def set_prometheus_metrics(metrics) -> None:
    """Set the PrometheusMetrics instance for feature store instrumentation."""
    global _prometheus_metrics
    _prometheus_metrics = metrics


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

        start_time = time.monotonic()
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

            duration = time.monotonic() - start_time
            if _prometheus_metrics:
                _prometheus_metrics.record_feature_ingestion(
                    feature_group, "put", duration, "success"
                )

            self.logger.debug(
                "Features stored",
                entity_id=entity_id,
                feature_group=feature_group,
                feature_count=len(features),
                ttl_seconds=ttl_seconds,
            )

        except Exception as e:
            duration = time.monotonic() - start_time
            if _prometheus_metrics:
                _prometheus_metrics.record_feature_ingestion(
                    feature_group, "put", duration, "error"
                )
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
                        FeatureStoreModel.is_active.is_(True),
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

    def bulk_put_features(
        self,
        entities: List[Tuple[str, Dict[str, Any]]],
        feature_group: str,
        event_timestamp: Optional[datetime] = None,
        ttl_seconds: Optional[int] = None,
    ) -> int:
        """Store features for multiple entities in batched operations.

        Uses INSERT ... ON CONFLICT DO UPDATE for PostgreSQL bulk upserts
        and Redis pipeline for batched cache writes. Much more efficient
        than calling put_features() in a loop.

        Args:
            entities: List of (entity_id, features_dict) tuples.
            feature_group: Feature group name.
            event_timestamp: Timestamp of the event (defaults to now).
            ttl_seconds: TTL for cached features (defaults to config value).

        Returns:
            Number of entities written.
        """
        if not entities:
            return 0

        if event_timestamp is None:
            event_timestamp = datetime.now(timezone.utc)
        if ttl_seconds is None:
            ttl_seconds = self.default_ttl

        ttl_timestamp = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        written = 0
        start_time = time.monotonic()

        try:
            # --- Redis batch write via pipeline ---
            try:
                pipe = self.redis_client.pipeline(transaction=False)
                for entity_id, features in entities:
                    cache_key = self._build_cache_key(entity_id, feature_group)
                    cached_data = {
                        "features": features,
                        "event_timestamp": event_timestamp.isoformat(),
                        "feature_group": feature_group,
                        "entity_id": entity_id,
                    }
                    serialized = pickle.dumps(cached_data)
                    pipe.setex(cache_key, ttl_seconds, serialized)
                pipe.execute()
            except Exception as e:
                self.logger.warning(
                    "Redis bulk write failed, continuing with DB write",
                    feature_group=feature_group,
                    error=str(e),
                )

            # --- PostgreSQL batch upsert via raw SQL ---
            self._bulk_persist_features(
                entities, feature_group, event_timestamp, ttl_timestamp
            )
            written = len(entities)

            duration = time.monotonic() - start_time
            if _prometheus_metrics:
                _prometheus_metrics.record_feature_ingestion(
                    feature_group, "bulk_put", duration, "success"
                )

            self.logger.debug(
                "Bulk features stored",
                feature_group=feature_group,
                entity_count=written,
            )

        except Exception as e:
            duration = time.monotonic() - start_time
            if _prometheus_metrics:
                _prometheus_metrics.record_feature_ingestion(
                    feature_group, "bulk_put", duration, "error"
                )
            self.logger.error(
                "Failed to bulk store features",
                feature_group=feature_group,
                entity_count=len(entities),
                error=str(e),
            )
            raise

        return written

    def _bulk_persist_features(
        self,
        entities: List[Tuple[str, Dict[str, Any]]],
        feature_group: str,
        event_timestamp: datetime,
        ttl_timestamp: datetime,
        max_retries: int = 3,
    ) -> None:
        """Persist features for multiple entities using batch upsert.

        JSONB model: one row per entity (not per feature), with all features
        stored as a single JSON object. Uses INSERT ... ON CONFLICT with JSONB
        merge (||) for PostgreSQL, or ORM merge for other dialects.

        Entities are sorted by entity_id to ensure consistent lock ordering
        and prevent deadlocks when multiple Beam workers write concurrently.
        Retries with exponential backoff on deadlock detection.
        """
        import json as json_mod
        import uuid

        # Sort by entity_id for consistent lock ordering (prevents deadlocks)
        sorted_entities = sorted(entities, key=lambda x: x[0])

        rows = []
        for entity_id, features in sorted_entities:
            rows.append(
                {
                    "id": str(uuid.uuid4()),
                    "entity_id": entity_id,
                    "feature_group": feature_group,
                    "features": json_mod.dumps(features),
                    "event_timestamp": event_timestamp,
                    "ingestion_timestamp": datetime.now(timezone.utc),
                    "ttl_timestamp": ttl_timestamp,
                    "is_active": True,
                    "feature_version": "1.0",
                    "tags": "{}",
                }
            )

        if not rows:
            return

        chunk_size = 5000  # 1 row per entity now (up from 500)

        for attempt in range(max_retries):
            try:
                with get_session() as session:
                    bind = session.get_bind()
                    dialect = (
                        bind.dialect.name if hasattr(bind, "dialect") else "unknown"
                    )

                    if dialect == "postgresql":
                        stmt = text(
                            """
                            INSERT INTO feature_store (
                                id, entity_id, feature_group, features,
                                event_timestamp, ingestion_timestamp, ttl_timestamp,
                                is_active, feature_version, tags
                            ) VALUES (
                                :id, :entity_id, :feature_group,
                                CAST(:features AS jsonb), :event_timestamp,
                                :ingestion_timestamp, :ttl_timestamp,
                                :is_active, :feature_version, CAST(:tags AS jsonb)
                            )
                            ON CONFLICT (entity_id, feature_group)
                            DO UPDATE SET
                                features = feature_store.features || EXCLUDED.features,
                                event_timestamp = EXCLUDED.event_timestamp,
                                ingestion_timestamp = EXCLUDED.ingestion_timestamp,
                                ttl_timestamp = EXCLUDED.ttl_timestamp,
                                is_active = true
                        """
                        )
                        for i in range(0, len(rows), chunk_size):
                            session.execute(stmt, rows[i : i + chunk_size])
                    else:
                        # Fallback for SQLite / other dialects: use ORM merge
                        for row in rows:
                            row["features"] = json_mod.loads(row["features"])
                            row["tags"] = {}
                            record = FeatureStoreModel(**row)
                            session.merge(record)
                return  # Success
            except Exception as e:
                is_deadlock = "deadlock" in str(e).lower()
                if is_deadlock and attempt < max_retries - 1:
                    wait = 0.1 * (2**attempt)  # 0.1s, 0.2s, 0.4s
                    self.logger.warning(
                        "Deadlock detected, retrying",
                        feature_group=feature_group,
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        wait_seconds=wait,
                    )
                    time.sleep(wait)
                    # Regenerate UUIDs for retry
                    for row in rows:
                        row["id"] = str(uuid.uuid4())
                else:
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

        JSONB model: upserts a single row per (entity_id, feature_group),
        merging incoming features into the existing JSON object.

        Args:
            entity_id: Entity identifier
            feature_group: Feature group name
            features: Feature dictionary
            event_timestamp: Event timestamp
            ttl_seconds: TTL in seconds
        """
        import json as json_mod
        import uuid

        ttl_timestamp = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

        with get_session() as session:
            bind = session.get_bind()
            dialect = bind.dialect.name if hasattr(bind, "dialect") else "unknown"

            if dialect == "postgresql":
                stmt = text(
                    """
                    INSERT INTO feature_store (
                        id, entity_id, feature_group, features,
                        event_timestamp, ingestion_timestamp, ttl_timestamp, is_active
                    ) VALUES (
                        :id, :entity_id, :feature_group,
                        CAST(:features AS jsonb), :event_timestamp,
                        now(), :ttl_timestamp, true
                    )
                    ON CONFLICT (entity_id, feature_group)
                    DO UPDATE SET
                        features = feature_store.features || EXCLUDED.features,
                        event_timestamp = EXCLUDED.event_timestamp,
                        ingestion_timestamp = now(),
                        ttl_timestamp = EXCLUDED.ttl_timestamp,
                        is_active = true
                """
                )
                session.execute(
                    stmt,
                    {
                        "id": str(uuid.uuid4()),
                        "entity_id": entity_id,
                        "feature_group": feature_group,
                        "features": json_mod.dumps(features),
                        "event_timestamp": event_timestamp,
                        "ttl_timestamp": ttl_timestamp,
                    },
                )
            else:
                # Fallback for SQLite / other dialects: use ORM merge
                # Try to find existing record and merge features
                existing = (
                    session.query(FeatureStoreModel)
                    .filter(
                        FeatureStoreModel.entity_id == entity_id,
                        FeatureStoreModel.feature_group == feature_group,
                    )
                    .first()
                )
                if existing:
                    merged = {**(existing.features or {}), **features}
                    existing.features = merged
                    existing.event_timestamp = event_timestamp
                    existing.ttl_timestamp = ttl_timestamp
                    existing.is_active = True
                else:
                    record = FeatureStoreModel(
                        entity_id=entity_id,
                        feature_group=feature_group,
                        features=features,
                        event_timestamp=event_timestamp,
                        ttl_timestamp=ttl_timestamp,
                    )
                    session.add(record)

    def _get_features_from_db(
        self,
        entity_id: str,
        feature_group: str,
        feature_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Retrieve features from database.

        Single-row fetch: returns the JSONB `features` column directly.

        Args:
            entity_id: Entity identifier
            feature_group: Feature group name
            feature_names: Optional list of specific features

        Returns:
            Feature dictionary
        """
        with get_session() as session:
            record = (
                session.query(FeatureStoreModel)
                .filter(
                    FeatureStoreModel.entity_id == entity_id,
                    FeatureStoreModel.feature_group == feature_group,
                    FeatureStoreModel.is_active.is_(True),
                )
                .first()
            )

            if record is None:
                return {}

            features = record.features or {}
            if feature_names:
                return {k: v for k, v in features.items() if k in feature_names}
            return features

    def _get_batch_features_from_db(
        self,
        entity_ids: List[str],
        feature_group: str,
        feature_names: Optional[List[str]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Retrieve batch features from database.

        Single row per entity: no multi-row reconstruction needed.

        Args:
            entity_ids: List of entity identifiers
            feature_group: Feature group name
            feature_names: Optional list of specific features

        Returns:
            Dictionary mapping entity_id -> feature dictionary
        """
        with get_session() as session:
            records = (
                session.query(FeatureStoreModel)
                .filter(
                    FeatureStoreModel.entity_id.in_(entity_ids),
                    FeatureStoreModel.feature_group == feature_group,
                    FeatureStoreModel.is_active.is_(True),
                )
                .all()
            )

            result = {}
            for record in records:
                features = record.features or {}
                if feature_names:
                    features = {k: v for k, v in features.items() if k in feature_names}
                result[record.entity_id] = features

            return result

