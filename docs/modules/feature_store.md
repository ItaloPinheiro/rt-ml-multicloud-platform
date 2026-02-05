# Feature Store Module

The Feature Store (`src/feature_store`) is a critical component that manages feature data consistency between training and serving.

## Architecture

The Feature Store uses a dual-storage architecture:
1.  **Online Store (Redis)**: Low-latency access for real-time predictions.
2.  **Offline Store (PostgreSQL)**: Durable storage for historical data and batch training.

## Key Components

### `FeatureStore`
Low-level interface for raw feature access.

*   `put_features(entity_id, feature_group, features)`
*   `get_features(entity_id, feature_group)`
*   `get_batch_features(entity_ids, feature_group)`

### `FeatureStoreClient`
High-level client that adds transformation logic.

*   `register_transform(feature_name, transform)`
*   `create_feature_vector(entity_id, feature_groups)`

## Transformations

Features can be transformed on-the-fly during retrieval or storage.

*   **NumericTransform**: Scaling, min/max clipping, missing value imputation.
*   **CategoricalTransform**: One-hot encoding (if needed), valid category checking.

## Usage Example

```python
from src.feature_store.client import FeatureStoreClient

client = FeatureStoreClient()

# Store features
client.put_features(
    entity_id="user_123",
    feature_group="user_stats",
    features={"age": 30, "total_purchases": 150.5}
)

# Retrieve features
features = client.get_features(
    entity_id="user_123",
    feature_group="user_stats"
)
```
