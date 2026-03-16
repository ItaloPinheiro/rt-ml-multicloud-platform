# Feature Store Bulk Upsert Optimization

## Problem Statement

The Feature Store uses an Entity-Attribute-Value (EAV) data model where each feature is stored as a separate row. For N entities with M features, this creates N x M rows per batch write. With ~40 features per entity, a 100-entity batch produces 4,000 PostgreSQL rows, each requiring a 4-column `ON CONFLICT` check.

**Current performance (100 events / 400 entities accumulated):**
- 25 seconds per 100-entity batch
- ~50 seconds total for 400 entities in beam-ingestion Job
- Projected: **~42 minutes for 10,000 entities**, **~7 hours for 100,000 entities**

**Target:** Support 1M entity_ids with sub-minute Feature Store writes during ingestion.

---

## Root Cause Analysis

### 1. EAV Row Explosion

```
100 entities x 40 features = 4,000 rows per batch
1M entities x 40 features = 40,000,000 rows total
```

Current schema (`feature_store` table):
```
id | entity_id | feature_group | feature_name | feature_value | data_type | event_timestamp | ...
```

Each feature is a separate row with its own UUID, JSON-serialized value, and data_type classification.

### 2. Expensive Unique Constraint

```sql
ON CONFLICT (entity_id, feature_group, feature_name, event_timestamp)
DO UPDATE SET feature_value = EXCLUDED.feature_value, ...
```

The 4-column composite unique constraint `uq_feature_store_entity_feature_time` includes `event_timestamp`. Since `event_timestamp` is set to `datetime.now()` per batch in `bulk_put_features()`, it differs between runs. PostgreSQL rarely finds a matching row, forcing a full INSERT + index rebuild instead of a cheap UPDATE-in-place.

### 3. Small Chunk Size

`chunk_size = 500` means 4,000 rows requires 8 separate `session.execute()` calls, each with its own transaction overhead and index maintenance pass.

### 4. Per-Row Overhead

Each row requires: `uuid4()` generation, `json.dumps()` serialization, `data_type` classification, and timestamp creation — all in a Python loop.

---

## Current Access Patterns

All consumers that must remain compatible with any schema change:

| Component | Operation | Method | Data Shape |
|---|---|---|---|
| Beam `WriteToFeatureStore` | Write (bulk) | `bulk_put_features([(entity_id, {f: v}), ...])` | Flat dict per entity |
| API `/predict` | Read (single) | `get_features(entity_id, feature_group)` | Returns `{feature_name: value}` |
| API `/features/{entity_id}` | Read (single) | `get_features(entity_id, group)` per group | Returns `{feature_name: value}` |
| API `/features/groups` | Read (metadata) | `get_feature_groups()` | Returns `[group_name, ...]` |
| API `/features/stats/{group}` | Read (aggregation) | `get_feature_statistics(group)` | Counts, distributions |
| Training `train.py` | Read (bulk) | Raw SQL: `SELECT entity_id, feature_name, feature_value WHERE ...` + pivot | EAV -> wide DataFrame |
| Assembly `assemble_training_data.py` | Read (bulk) | Raw SQL: `SELECT entity_id, feature_name, feature_value WHERE ...` + pivot | EAV -> wide DataFrame |
| `FeatureStoreClient` | Read (vector) | `create_feature_vector(entity_id, groups, schema)` | Multi-group merged dict |
| Redis cache | Read/Write | `features:{group}:{entity_id}` -> pickled dict | Flat dict (already JSONB-like) |
| `reset-demo.sh` | Delete | `TRUNCATE feature_store CASCADE` | N/A |
| `cleanup_expired_features()` | Update | `UPDATE ... SET is_active=False WHERE ttl_timestamp <= now()` | N/A |

**Key insight:** Redis already stores features as a single pickled dict per entity per group. Only PostgreSQL uses EAV. The API and Beam transforms all work with flat dicts `{feature_name: value}` — the EAV decomposition is an internal detail of `_persist_features` / `_bulk_persist_features`.

---

## Proposed Solution: JSONB Column Model

Replace the EAV model with a single JSONB column per entity per feature group. This matches the Redis storage pattern and eliminates the row explosion.

### New Schema

```sql
CREATE TABLE feature_store (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       VARCHAR(255) NOT NULL,
    feature_group   VARCHAR(255) NOT NULL,
    features        JSONB NOT NULL,              -- all features as one JSON object
    event_timestamp TIMESTAMPTZ NOT NULL,
    ingestion_timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    feature_version VARCHAR(100) DEFAULT '1.0',
    source_system   VARCHAR(255),
    tags            JSONB DEFAULT '{}',
    ttl_timestamp   TIMESTAMPTZ,
    is_active       BOOLEAN NOT NULL DEFAULT true,

    CONSTRAINT uq_feature_store_entity_group
        UNIQUE (entity_id, feature_group)
);

CREATE INDEX idx_feature_store_entity_group_active
    ON feature_store (entity_id, feature_group)
    WHERE is_active = true;

CREATE INDEX idx_feature_store_group
    ON feature_store (feature_group);

CREATE INDEX idx_feature_store_ttl
    ON feature_store (ttl_timestamp)
    WHERE is_active = true;

CREATE INDEX idx_feature_store_features_gin
    ON feature_store USING GIN (features);
```

### Row Count Comparison

| Scenario | EAV Rows | JSONB Rows | Reduction |
|---|---|---|---|
| 100 entities x 40 features | 4,000 | 100 | 40x |
| 10,000 entities x 40 features | 400,000 | 10,000 | 40x |
| 1M entities x 40 features | 40,000,000 | 1,000,000 | 40x |

### Upsert Query

```sql
INSERT INTO feature_store (
    id, entity_id, feature_group, features,
    event_timestamp, ingestion_timestamp, ttl_timestamp, is_active
) VALUES (
    :id, :entity_id, :feature_group, :features,
    :event_timestamp, :ingestion_timestamp, :ttl_timestamp, true
)
ON CONFLICT (entity_id, feature_group)
DO UPDATE SET
    features = feature_store.features || EXCLUDED.features,
    event_timestamp = EXCLUDED.event_timestamp,
    ingestion_timestamp = EXCLUDED.ingestion_timestamp,
    ttl_timestamp = EXCLUDED.ttl_timestamp,
    is_active = true
```

The `||` operator merges the incoming JSONB into the existing one, so incremental feature updates don't overwrite unrelated features. For full replacement, use `EXCLUDED.features` instead.

---

## Performance Projections

### Write Performance (bulk_put_features)

| Entities | EAV (current) | JSONB (proposed) | Speedup |
|---|---|---|---|
| 100 | 25s | <1s | ~25x |
| 1,000 | ~4 min | ~2s | ~120x |
| 10,000 | ~42 min | ~15s | ~170x |
| 100,000 | ~7 hours | ~2 min | ~200x |
| 1,000,000 | ~70 hours | ~20 min | ~210x |

Projections based on:
- JSONB: ~1,000 single-row upserts/sec on t3.medium PostgreSQL (conservative)
- With `chunk_size=5000` and `executemany`: ~5,000 upserts/sec
- With `COPY` for initial load: ~50,000 rows/sec

### Read Performance (get_features)

| Operation | EAV (current) | JSONB (proposed) |
|---|---|---|
| Single entity lookup | Index scan on composite + reconstruct dict from N rows | Single row fetch, return `features` column directly |
| Batch 100 entities | 100 x N row fetches + Python dict assembly | 100 single-row fetches |
| Training data pivot | `SELECT ... pivot_table()` in Python (N x M rows) | `SELECT entity_id, features FROM ... WHERE feature_group = ...` — no pivot needed |

### Storage

| 1M entities x 40 features | EAV | JSONB |
|---|---|---|
| Row count | 40M | 1M |
| Estimated size (with indexes) | ~12 GB | ~800 MB |
| Index size | ~8 GB (7 indexes) | ~200 MB (3 indexes) |

---

## Implementation Plan

### Phase 1: Database Migration

Create a new migration that:

1. Add the `features` JSONB column to the existing table
2. Populate it from the EAV data: `UPDATE feature_store SET features = (SELECT jsonb_object_agg(...) ...)`
3. Add the new unique constraint `(entity_id, feature_group)`
4. Drop the old unique constraint and per-feature indexes

**Migration script** (run inside K8s via `kubectl exec`):

```sql
-- Step 1: Add JSONB column
ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS features JSONB;

-- Step 2: Backfill JSONB from EAV rows (idempotent)
WITH aggregated AS (
    SELECT entity_id, feature_group,
           jsonb_object_agg(feature_name, feature_value) AS features_json,
           MAX(event_timestamp) AS latest_event,
           MAX(ingestion_timestamp) AS latest_ingestion,
           MAX(ttl_timestamp) AS latest_ttl
    FROM feature_store
    WHERE is_active = true
    GROUP BY entity_id, feature_group
)
UPDATE feature_store f
SET features = a.features_json
FROM aggregated a
WHERE f.entity_id = a.entity_id
  AND f.feature_group = a.feature_group
  AND f.is_active = true;

-- Step 3: Deduplicate — keep one row per (entity_id, feature_group)
DELETE FROM feature_store
WHERE id NOT IN (
    SELECT DISTINCT ON (entity_id, feature_group) id
    FROM feature_store
    WHERE is_active = true
    ORDER BY entity_id, feature_group, ingestion_timestamp DESC
);

-- Step 4: Drop old constraints and indexes
ALTER TABLE feature_store DROP CONSTRAINT IF EXISTS uq_feature_store_entity_feature_time;
DROP INDEX IF EXISTS idx_feature_store_feature_name;
DROP INDEX IF EXISTS idx_feature_store_entity_feature;
DROP INDEX IF EXISTS idx_feature_store_event_timestamp;
DROP INDEX IF EXISTS idx_feature_store_ingestion_timestamp;

-- Step 5: Drop EAV columns
ALTER TABLE feature_store DROP COLUMN IF EXISTS feature_name;
ALTER TABLE feature_store DROP COLUMN IF EXISTS feature_value;
ALTER TABLE feature_store DROP COLUMN IF EXISTS data_type;

-- Step 6: Add new unique constraint and indexes
ALTER TABLE feature_store
    ADD CONSTRAINT uq_feature_store_entity_group UNIQUE (entity_id, feature_group);

CREATE INDEX IF NOT EXISTS idx_feature_store_entity_group_active
    ON feature_store (entity_id, feature_group) WHERE is_active = true;

CREATE INDEX IF NOT EXISTS idx_feature_store_ttl_active
    ON feature_store (ttl_timestamp) WHERE is_active = true;

-- Optional: GIN index for querying individual features within JSONB
-- Only add if you need WHERE features->>'amount' > '500' type queries
-- CREATE INDEX IF NOT EXISTS idx_feature_store_features_gin
--     ON feature_store USING GIN (features);
```

### Phase 2: Update SQLAlchemy Model

**`src/database/models.py`** — Replace EAV columns with JSONB:

```python
class FeatureStore(Base):
    __tablename__ = "feature_store"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id = Column(String(255), nullable=False)
    feature_group = Column(String(255), nullable=False)
    features = Column(JSON, nullable=False)          # replaces feature_name + feature_value + data_type
    event_timestamp = Column(DateTime, nullable=False)
    ingestion_timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    feature_version = Column(String(100), default="1.0")
    source_system = Column(String(255))
    tags = Column(JSON, default=dict)
    ttl_timestamp = Column(DateTime)
    is_active = Column(Boolean, default=True, nullable=False)

    __table_args__ = (
        Index("idx_feature_store_entity_group_active", "entity_id", "feature_group",
              postgresql_where=text("is_active = true")),
        Index("idx_feature_store_group", "feature_group"),
        Index("idx_feature_store_ttl_active", "ttl_timestamp",
              postgresql_where=text("is_active = true")),
        UniqueConstraint("entity_id", "feature_group",
                         name="uq_feature_store_entity_group"),
    )
```

### Phase 3: Update FeatureStore Methods

**`src/feature_store/store.py`** — Changes to each method:

#### `bulk_put_features()` — eliminate EAV explosion

```python
def _bulk_persist_features(self, entities, feature_group, event_timestamp, ttl_timestamp):
    import json as json_mod
    import uuid

    rows = []
    for entity_id, features in entities:
        rows.append({
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
        })

    if not rows:
        return

    chunk_size = 5000  # up from 500; 1 row per entity now

    with get_session() as session:
        bind = session.get_bind()
        dialect = bind.dialect.name if hasattr(bind, "dialect") else "unknown"

        if dialect == "postgresql":
            stmt = text("""
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
            """)
            for i in range(0, len(rows), chunk_size):
                session.execute(stmt, rows[i:i + chunk_size])
        else:
            for row in rows:
                row["features"] = json_mod.loads(row["features"])
                row["tags"] = {}
                record = FeatureStoreModel(**row)
                session.merge(record)
```

Key changes:
- **1 row per entity** instead of 1 row per feature (40x reduction)
- **`chunk_size = 5000`** (covers 5000 entities per round trip)
- **2-column conflict** `(entity_id, feature_group)` instead of 4-column
- **JSONB merge** `||` operator preserves existing features not in current batch

#### `put_features()` — single entity write

```python
def _persist_features(self, entity_id, feature_group, features, event_timestamp, ttl_seconds):
    ttl_timestamp = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    with get_session() as session:
        bind = session.get_bind()
        dialect = bind.dialect.name if hasattr(bind, "dialect") else "unknown"
        if dialect == "postgresql":
            stmt = text("""
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
            """)
            session.execute(stmt, {
                "id": str(uuid.uuid4()),
                "entity_id": entity_id,
                "feature_group": feature_group,
                "features": json.dumps(features),
                "event_timestamp": event_timestamp,
                "ttl_timestamp": ttl_timestamp,
            })
        else:
            record = FeatureStoreModel(
                entity_id=entity_id,
                feature_group=feature_group,
                features=features,
                event_timestamp=event_timestamp,
                ttl_timestamp=ttl_timestamp,
            )
            session.merge(record)
```

#### `get_features()` — simplified read

```python
def _get_features_from_db(self, entity_id, feature_group, feature_names=None):
    with get_session() as session:
        record = session.query(FeatureStoreModel).filter(
            FeatureStoreModel.entity_id == entity_id,
            FeatureStoreModel.feature_group == feature_group,
            FeatureStoreModel.is_active.is_(True),
        ).first()

        if record is None:
            return {}

        features = record.features or {}
        if feature_names:
            return {k: v for k, v in features.items() if k in feature_names}
        return features
```

No more multi-row reconstruction — single row, single JSON read.

#### `get_batch_features_from_db()` — simplified batch read

```python
def _get_batch_features_from_db(self, entity_ids, feature_group, feature_names=None):
    with get_session() as session:
        records = session.query(FeatureStoreModel).filter(
            FeatureStoreModel.entity_id.in_(entity_ids),
            FeatureStoreModel.feature_group == feature_group,
            FeatureStoreModel.is_active.is_(True),
        ).all()

        result = {}
        for record in records:
            features = record.features or {}
            if feature_names:
                features = {k: v for k, v in features.items() if k in feature_names}
            result[record.entity_id] = features
        return result
```

#### `get_feature_statistics()` — use JSONB functions

```python
# In client.py get_feature_statistics()
# Replace per-row aggregation with JSONB key extraction:
stmt = text("""
    SELECT
        COUNT(DISTINCT entity_id) AS entity_count,
        COUNT(*) AS row_count,
        jsonb_object_keys(features) AS feature_name
    FROM feature_store
    WHERE feature_group = :group AND is_active = true
    GROUP BY feature_name
""")
```

### Phase 4: Update Training Data Readers

**`src/models/training/train.py`** `load_data_from_feature_store()`:

Replace EAV query + pivot with direct JSONB read:

```python
# Before (EAV): N x M rows, then pivot_table()
stmt = select(
    FeatureStoreModel.entity_id,
    FeatureStoreModel.feature_name,
    FeatureStoreModel.feature_value,
).where(...)

# After (JSONB): N rows, no pivot needed
stmt = select(
    FeatureStoreModel.entity_id,
    FeatureStoreModel.features,
).where(
    FeatureStoreModel.feature_group.in_(feature_groups),
    FeatureStoreModel.is_active.is_(True),
)

rows = []
for record in session.execute(stmt).yield_per(10_000):
    entity_id, features = record
    features["entity_id"] = entity_id
    rows.append(features)

df = pd.DataFrame(rows)
# No pivot needed — already wide format
```

**`src/feature_engineering/assemble_training_data.py`** `_read_from_feature_store()`:

Same pattern — replace EAV pivot with direct JSONB DataFrame construction.

### Phase 5: Update Tests

Update unit and integration tests to use `features` JSONB column instead of `feature_name`/`feature_value`/`data_type` columns. The test assertions for `get_features()` and `get_batch_features()` should not change since they return the same `{name: value}` dict shape.

---

## Further Scaling (Beyond 1M)

For datasets significantly larger than 1M entities:

### Partitioning

```sql
CREATE TABLE feature_store (
    ...
) PARTITION BY HASH (entity_id);

CREATE TABLE feature_store_p0 PARTITION OF feature_store FOR VALUES WITH (MODULUS 8, REMAINDER 0);
CREATE TABLE feature_store_p1 PARTITION OF feature_store FOR VALUES WITH (MODULUS 8, REMAINDER 1);
-- ... up to p7
```

Hash partitioning on `entity_id` distributes writes evenly and allows parallel bulk loads. Each partition gets its own index, reducing B-tree depth.

### COPY-Based Bulk Load

For initial/full loads, use PostgreSQL `COPY` instead of `INSERT ... ON CONFLICT`:

```python
import io, csv
buf = io.StringIO()
writer = csv.writer(buf)
for entity_id, features in entities:
    writer.writerow([entity_id, feature_group, json.dumps(features), ...])
buf.seek(0)

with get_session() as session:
    conn = session.connection().connection
    with conn.cursor() as cur:
        cur.copy_expert(
            "COPY feature_store_staging FROM STDIN WITH CSV",
            buf
        )
    # Then merge from staging to main table
```

`COPY` throughput: ~50,000-100,000 rows/sec vs ~5,000 rows/sec for batched INSERT.

### Read Replicas for Training

Training data reads are heavy and can compete with real-time serving writes. Use a PostgreSQL read replica for `load_data_from_feature_store()` and `_read_from_feature_store()` to avoid impacting write latency.

### Redis Cluster for Hot Cache

For 1M+ entities with high read QPS, a single Redis instance becomes a bottleneck. Redis Cluster with hash-slot-based sharding on `{feature_group}:{entity_id}` distributes the cache across nodes.

---

## Risk Mitigation

1. **Backward compatibility**: The migration is a one-way schema change. Run the migration on a database snapshot first to verify.
2. **Zero-downtime**: The migration can run while the API is serving if done in phases (add column -> backfill -> swap code -> drop old columns).
3. **Rollback**: Before dropping EAV columns (Phase 1 Step 5), verify all consumers work with JSONB. Keep the old columns for one release cycle if needed.
4. **Data validation**: After backfill, compare `features` JSONB content against original EAV rows for a sample of entities.

---

## Summary

| Metric | EAV (current) | JSONB (proposed) |
|---|---|---|
| Rows per 100 entities | 4,000 | 100 |
| Write time (100 entities) | 25s | <1s |
| Write time (1M entities) | ~70 hours | ~20 min |
| Unique constraint columns | 4 | 2 |
| Read: single entity | N rows + dict assembly | 1 row, direct return |
| Training data read | N x M rows + pivot | N rows, no pivot |
| Storage (1M entities) | ~12 GB | ~800 MB |
| Index count | 7 | 3 |
