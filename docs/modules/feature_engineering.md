# Feature Engineering Module

The feature engineering module (`src/feature_engineering`) is responsible for transforming raw data streams into usable features for machine learning models.

## Apache Beam Pipelines

We use **Apache Beam** to define portable data processing pipelines that can run on various runners (Direct, Flink, Dataflow).

### Pipeline Structure

1.  **Read**: Consume data from `StreamIngestion` sources.
2.  **Window**: Group data into time windows (Fixed, Sliding, Session).
3.  **Process**: Apply transformations (aggregations, normalization).
4.  **Write**: Store results in the Feature Store.

## Transforms

Custom Beam `DoFn`s are implemented in `src/feature_engineering/beam/transforms.py`.

*   `ExtractFeaturesFn`: Parses raw message data.
*   `CalculateAggregatesFn`: Computes rolling averages, counts, etc.
*   `WriteToFeatureStoreFn`: Writes the final features to Redis/DB.

## Running Pipelines

Pipelines can be executed locally for testing or submitted to a cluster for production.

```bash
# Run locally
python -m src.feature_engineering.main --runner DirectRunner
```
