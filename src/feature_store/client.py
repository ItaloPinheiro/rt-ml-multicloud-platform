"""Feature store client for simplified feature access and management."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

from .store import FeatureStore
from .transforms import CategoricalTransform, FeatureTransform, NumericTransform

logger = structlog.get_logger()


class FeatureStoreClient:
    """High-level client for feature store operations with built-in transformations."""

    def __init__(self, feature_store: Optional[FeatureStore] = None):
        """Initialize feature store client.

        Args:
            feature_store: Optional feature store instance. If None, will create one.
        """
        self.feature_store = feature_store or FeatureStore()
        self.transforms: Dict[str, FeatureTransform] = {}
        self.logger = logger.bind(component="FeatureStoreClient")

    def register_transform(
        self, feature_name: str, transform: FeatureTransform
    ) -> None:
        """Register a feature transformation.

        Args:
            feature_name: Name of the feature to transform
            transform: Transformation to apply
        """
        self.transforms[feature_name] = transform
        self.logger.debug(
            "Feature transform registered",
            feature_name=feature_name,
            transform_type=type(transform).__name__,
        )

    def put_features(
        self,
        entity_id: str,
        feature_group: str,
        features: Dict[str, Any],
        apply_transforms: bool = True,
        event_timestamp: Optional[datetime] = None,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """Store features with optional transformations.

        Args:
            entity_id: Unique identifier for the entity
            feature_group: Feature group name
            features: Dictionary of feature name -> value
            apply_transforms: Whether to apply registered transformations
            event_timestamp: Timestamp of the event
            ttl_seconds: TTL for cached features
        """
        try:
            # Apply transformations if requested
            if apply_transforms:
                features = self._apply_transforms(features)

            # Store features
            self.feature_store.put_features(
                entity_id=entity_id,
                feature_group=feature_group,
                features=features,
                event_timestamp=event_timestamp,
                ttl_seconds=ttl_seconds,
            )

            self.logger.debug(
                "Features stored via client",
                entity_id=entity_id,
                feature_group=feature_group,
                feature_count=len(features),
                transforms_applied=apply_transforms,
            )

        except Exception as e:
            self.logger.error(
                "Failed to store features via client",
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
        apply_transforms: bool = False,
    ) -> Dict[str, Any]:
        """Retrieve features with optional transformations.

        Args:
            entity_id: Unique identifier for the entity
            feature_group: Feature group name
            feature_names: Optional list of specific features to retrieve
            apply_transforms: Whether to apply registered transformations

        Returns:
            Dictionary of feature name -> value
        """
        try:
            # Retrieve features
            features = self.feature_store.get_features(
                entity_id=entity_id,
                feature_group=feature_group,
                feature_names=feature_names,
            )

            # Apply transformations if requested
            if apply_transforms:
                features = self._apply_transforms(features)

            self.logger.debug(
                "Features retrieved via client",
                entity_id=entity_id,
                feature_group=feature_group,
                feature_count=len(features),
                transforms_applied=apply_transforms,
            )

            return features

        except Exception as e:
            self.logger.error(
                "Failed to retrieve features via client",
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
        apply_transforms: bool = False,
    ) -> Dict[str, Dict[str, Any]]:
        """Retrieve features for multiple entities with optional transformations.

        Args:
            entity_ids: List of entity identifiers
            feature_group: Feature group name
            feature_names: Optional list of specific features to retrieve
            apply_transforms: Whether to apply registered transformations

        Returns:
            Dictionary mapping entity_id -> feature dictionary
        """
        try:
            # Retrieve batch features
            batch_features = self.feature_store.get_batch_features(
                entity_ids=entity_ids,
                feature_group=feature_group,
                feature_names=feature_names,
            )

            # Apply transformations if requested
            if apply_transforms:
                for entity_id, features in batch_features.items():
                    batch_features[entity_id] = self._apply_transforms(features)

            self.logger.debug(
                "Batch features retrieved via client",
                feature_group=feature_group,
                entity_count=len(entity_ids),
                transforms_applied=apply_transforms,
            )

            return batch_features

        except Exception as e:
            self.logger.error(
                "Failed to retrieve batch features via client",
                feature_group=feature_group,
                entity_count=len(entity_ids),
                error=str(e),
            )
            raise

    def create_feature_vector(
        self,
        entity_id: str,
        feature_groups: List[str],
        feature_schema: Dict[str, List[str]],
        apply_transforms: bool = True,
        fill_missing: bool = True,
        default_value: Any = 0.0,
    ) -> Dict[str, Any]:
        """Create a complete feature vector from multiple feature groups.

        Args:
            entity_id: Entity identifier
            feature_groups: List of feature groups to include
            feature_schema: Dictionary mapping feature_group -> list of feature names
            apply_transforms: Whether to apply transformations
            fill_missing: Whether to fill missing features with default values
            default_value: Default value for missing features

        Returns:
            Complete feature vector dictionary
        """
        try:
            feature_vector = {}

            for feature_group in feature_groups:
                expected_features = feature_schema.get(feature_group, [])

                # Retrieve features for this group
                features = self.get_features(
                    entity_id=entity_id,
                    feature_group=feature_group,
                    feature_names=expected_features,
                    apply_transforms=apply_transforms,
                )

                # Fill missing features if requested
                if fill_missing:
                    for feature_name in expected_features:
                        if feature_name not in features:
                            features[feature_name] = default_value

                # Add to feature vector with group prefix
                for feature_name, value in features.items():
                    prefixed_name = f"{feature_group}_{feature_name}"
                    feature_vector[prefixed_name] = value

            self.logger.debug(
                "Feature vector created",
                entity_id=entity_id,
                feature_groups=feature_groups,
                total_features=len(feature_vector),
            )

            return feature_vector

        except Exception as e:
            self.logger.error(
                "Failed to create feature vector",
                entity_id=entity_id,
                feature_groups=feature_groups,
                error=str(e),
            )
            raise

    def create_batch_feature_vectors(
        self,
        entity_ids: List[str],
        feature_groups: List[str],
        feature_schema: Dict[str, List[str]],
        apply_transforms: bool = True,
        fill_missing: bool = True,
        default_value: Any = 0.0,
    ) -> Dict[str, Dict[str, Any]]:
        """Create feature vectors for multiple entities efficiently.

        Args:
            entity_ids: List of entity identifiers
            feature_groups: List of feature groups to include
            feature_schema: Dictionary mapping feature_group -> list of feature names
            apply_transforms: Whether to apply transformations
            fill_missing: Whether to fill missing features with default values
            default_value: Default value for missing features

        Returns:
            Dictionary mapping entity_id -> feature vector dictionary
        """
        try:
            entity_feature_vectors = {entity_id: {} for entity_id in entity_ids}

            for feature_group in feature_groups:
                expected_features = feature_schema.get(feature_group, [])

                # Retrieve batch features for this group
                batch_features = self.get_batch_features(
                    entity_ids=entity_ids,
                    feature_group=feature_group,
                    feature_names=expected_features,
                    apply_transforms=apply_transforms,
                )

                # Process each entity
                for entity_id in entity_ids:
                    features = batch_features.get(entity_id, {})

                    # Fill missing features if requested
                    if fill_missing:
                        for feature_name in expected_features:
                            if feature_name not in features:
                                features[feature_name] = default_value

                    # Add to feature vector with group prefix
                    for feature_name, value in features.items():
                        prefixed_name = f"{feature_group}_{feature_name}"
                        entity_feature_vectors[entity_id][prefixed_name] = value

            self.logger.debug(
                "Batch feature vectors created",
                entity_count=len(entity_ids),
                feature_groups=feature_groups,
                avg_features_per_entity=sum(
                    len(fv) for fv in entity_feature_vectors.values()
                )
                / len(entity_ids),
            )

            return entity_feature_vectors

        except Exception as e:
            self.logger.error(
                "Failed to create batch feature vectors",
                entity_count=len(entity_ids),
                feature_groups=feature_groups,
                error=str(e),
            )
            raise

    def setup_common_transforms(self) -> None:
        """Setup commonly used feature transformations."""
        # Numeric transformations
        self.register_transform(
            "amount",
            NumericTransform(
                min_value=0, max_value=10000, fill_missing=True, default_value=0.0
            ),
        )

        self.register_transform(
            "age",
            NumericTransform(
                min_value=0, max_value=120, fill_missing=True, default_value=30.0
            ),
        )

        # Categorical transformations
        self.register_transform(
            "merchant_category",
            CategoricalTransform(
                valid_categories=[
                    "electronics",
                    "grocery",
                    "gas",
                    "restaurant",
                    "retail",
                    "other",
                ],
                fill_missing=True,
                default_value="other",
            ),
        )

        self.register_transform(
            "payment_method",
            CategoricalTransform(
                valid_categories=["credit", "debit", "cash", "mobile"],
                fill_missing=True,
                default_value="credit",
            ),
        )

        self.logger.info("Common feature transforms registered")

    def get_feature_statistics(self, feature_group: str) -> Dict[str, Any]:
        """Get statistics about features in a feature group.

        Args:
            feature_group: Feature group name

        Returns:
            Dictionary with feature statistics
        """
        try:
            from sqlalchemy import func

            from ..database.models import FeatureStore as FeatureStoreModel
            from ..database.session import get_session

            with get_session() as session:
                # Get feature count by name
                feature_counts = (
                    session.query(
                        FeatureStoreModel.feature_name,
                        func.count(FeatureStoreModel.id).label("count"),
                    )
                    .filter(
                        FeatureStoreModel.feature_group == feature_group,
                        FeatureStoreModel.is_active.is_(True),
                    )
                    .group_by(FeatureStoreModel.feature_name)
                    .all()
                )

                # Get unique entity count
                entity_count = (
                    session.query(
                        func.count(func.distinct(FeatureStoreModel.entity_id))
                    )
                    .filter(
                        FeatureStoreModel.feature_group == feature_group,
                        FeatureStoreModel.is_active.is_(True),
                    )
                    .scalar()
                )

                # Get data type distribution
                data_type_counts = (
                    session.query(
                        FeatureStoreModel.data_type,
                        func.count(FeatureStoreModel.id).label("count"),
                    )
                    .filter(
                        FeatureStoreModel.feature_group == feature_group,
                        FeatureStoreModel.is_active.is_(True),
                    )
                    .group_by(FeatureStoreModel.data_type)
                    .all()
                )

                statistics = {
                    "feature_group": feature_group,
                    "unique_entities": entity_count,
                    "feature_counts": {name: count for name, count in feature_counts},
                    "data_type_distribution": {
                        dtype: count for dtype, count in data_type_counts
                    },
                    "total_features": sum(count for _, count in feature_counts),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

                self.logger.debug(
                    "Feature statistics retrieved",
                    feature_group=feature_group,
                    total_features=statistics["total_features"],
                    unique_entities=statistics["unique_entities"],
                )

                return statistics

        except Exception as e:
            self.logger.error(
                "Failed to get feature statistics",
                feature_group=feature_group,
                error=str(e),
            )
            raise

    def _apply_transforms(self, features: Dict[str, Any]) -> Dict[str, Any]:
        """Apply registered transformations to features.

        Args:
            features: Feature dictionary

        Returns:
            Transformed feature dictionary
        """
        transformed_features = {}

        for feature_name, value in features.items():
            if feature_name in self.transforms:
                try:
                    transformed_value = self.transforms[feature_name].transform(value)
                    transformed_features[feature_name] = transformed_value
                except Exception as e:
                    self.logger.warning(
                        "Feature transform failed, using original value",
                        feature_name=feature_name,
                        original_value=value,
                        error=str(e),
                    )
                    transformed_features[feature_name] = value
            else:
                transformed_features[feature_name] = value

        return transformed_features
