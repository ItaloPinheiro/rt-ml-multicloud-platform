"""Assemble training-ready CSV from Beam-produced feature files.

Reads sharded JSON-lines feature files (per-record + aggregated),
joins them by user_id, applies a labeling strategy, maps columns
per the model definition's beam_mapping config, and writes a CSV
ready for model training.

Usage:
  python -m src.feature_engineering.assemble_training_data \
    --features-path s3://bucket/features \
    --aggregated-path s3://bucket/aggregated \
    --output-path s3://bucket/datasets/fraud_detection.csv \
    --model-type fraud_detector \
    --labeling-strategy rule_based
"""

import argparse
import io
import json
import logging
import sys
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from src.feature_engineering.labeling import get_labeling_strategy
from src.models.model_definition import load_model_definition

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------


def _is_s3_path(path: str) -> bool:
    return path.startswith("s3://")


def _parse_s3_url(path: str) -> tuple[str, str]:
    """Split s3://bucket/prefix into (bucket, prefix)."""
    without_scheme = path[len("s3://") :]
    bucket, _, prefix = without_scheme.partition("/")
    return bucket, prefix


def _read_s3_jsonl(path: str) -> List[Dict[str, Any]]:
    """Read all sharded JSON-lines files from an S3 prefix."""
    import boto3

    bucket, prefix = _parse_s3_url(path)
    s3 = boto3.client("s3")

    # List all shard files under the prefix
    paginator = s3.get_paginator("list_objects_v2")
    keys: List[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".json"):
                keys.append(key)

    if not keys:
        raise FileNotFoundError(f"No .json files found at s3://{bucket}/{prefix}")

    records: List[Dict[str, Any]] = []
    for key in sorted(keys):
        logger.info("Reading s3://%s/%s", bucket, key)
        resp = s3.get_object(Bucket=bucket, Key=key)
        body = resp["Body"].read().decode("utf-8")
        for line in body.strip().splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))

    logger.info("Read %d records from %d shard(s) at %s", len(records), len(keys), path)
    return records


def _read_local_jsonl(path: str) -> List[Dict[str, Any]]:
    """Read all sharded JSON-lines files from a local directory prefix."""
    parent = Path(path).parent
    prefix = Path(path).name

    json_files = sorted(parent.glob(f"{prefix}*.json"))
    if not json_files:
        raise FileNotFoundError(f"No .json files matching {path}*.json")

    records: List[Dict[str, Any]] = []
    for fp in json_files:
        logger.info("Reading %s", fp)
        with open(fp) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

    logger.info(
        "Read %d records from %d file(s) at %s", len(records), len(json_files), path
    )
    return records


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    """Read JSON-lines from S3 or local path."""
    if _is_s3_path(path):
        return _read_s3_jsonl(path)
    return _read_local_jsonl(path)


def _read_from_feature_store(
    feature_groups: List[str],
    feature_schema: Dict[str, List[str]],
) -> tuple:
    """Read features from PostgreSQL feature store (cold storage).

    Returns per-record and aggregated DataFrames in the same format
    as _read_jsonl() produces, so downstream join/label/map logic
    works unchanged.
    """
    from sqlalchemy import select

    from src.database.models import FeatureStore as FeatureStoreModel
    from src.database.session import get_session

    def _query_group(group: str, feature_names: List[str]) -> pd.DataFrame:
        stmt = select(
            FeatureStoreModel.entity_id,
            FeatureStoreModel.feature_name,
            FeatureStoreModel.feature_value,
        ).where(
            FeatureStoreModel.feature_group == group,
            FeatureStoreModel.feature_name.in_(feature_names),
            FeatureStoreModel.is_active.is_(True),
        )
        with get_session() as session:
            result = session.execute(stmt).yield_per(10_000)
            chunks = []
            for partition in result.partitions():
                chunks.append(
                    pd.DataFrame(
                        partition,
                        columns=["entity_id", "feature_name", "feature_value"],
                    )
                )
            if not chunks:
                return pd.DataFrame()
            df = pd.concat(chunks, ignore_index=True)

        # Pivot EAV -> wide format (same shape as JSON-lines output)
        wide = df.pivot_table(
            index="entity_id",
            columns="feature_name",
            values="feature_value",
            aggfunc="first",
        ).reset_index()
        # Cast JSON values to numeric
        for col in wide.columns:
            if col != "entity_id":
                wide[col] = pd.to_numeric(wide[col], errors="coerce")
        wide = wide.rename(columns={"entity_id": "user_id"})
        return wide

    # Query each group from feature_schema keys
    # By convention, the first group is per-record, the rest are aggregated
    per_record_group = feature_groups[0]
    features_df = _query_group(
        per_record_group, feature_schema.get(per_record_group, [])
    )

    aggregated_dfs = []
    for group in feature_groups[1:]:
        agg_df = _query_group(group, feature_schema.get(group, []))
        # Rename "user_id" to "key" to match Beam output format
        if "user_id" in agg_df.columns:
            agg_df = agg_df.rename(columns={"user_id": "key"})
        aggregated_dfs.append(agg_df)

    # Merge all aggregated groups into one DataFrame
    if aggregated_dfs:
        aggregated_df = aggregated_dfs[0]
        for extra_df in aggregated_dfs[1:]:
            aggregated_df = aggregated_df.merge(extra_df, on="key", how="outer")
    else:
        aggregated_df = pd.DataFrame()

    return features_df, aggregated_df


def _write_parquet(df: pd.DataFrame, path: str) -> None:
    """Write DataFrame as Parquet to S3 or local path."""
    if _is_s3_path(path):
        import boto3

        buf = io.BytesIO()
        df.to_parquet(buf, index=False, engine="pyarrow")
        bucket, key = _parse_s3_url(path)
        boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
        logger.info("Wrote %d rows to s3://%s/%s (parquet)", len(df), bucket, key)
    else:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out, index=False, engine="pyarrow")
        logger.info("Wrote %d rows to %s (parquet)", len(df), out)


def _write_csv(df: pd.DataFrame, path: str) -> None:
    """Write DataFrame as CSV to S3 or local path."""
    if _is_s3_path(path):
        import boto3

        bucket, key = _parse_s3_url(path)
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        boto3.client("s3").put_object(
            Bucket=bucket, Key=key, Body=buf.getvalue().encode("utf-8")
        )
        logger.info("Wrote %d rows to s3://%s/%s", len(df), bucket, key)
    else:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, index=False)
        logger.info("Wrote %d rows to %s", len(df), out)


# ---------------------------------------------------------------------------
# Beam mapping config loader
# ---------------------------------------------------------------------------


def _load_beam_mapping(model_type: str) -> Dict[str, Any]:
    """Load beam_mapping section from a model definition YAML.

    Falls back to empty dict if the section is absent (backwards compat).
    """
    import yaml

    # Validate model exists (raises FileNotFoundError / ValueError if not)
    load_model_definition(model_type)

    # Re-read raw YAML to get beam_mapping (not part of ModelDefinition dataclass)
    from src.models.model_definition import _DEFAULT_DEFINITIONS_PATH

    yaml_path = Path(_DEFAULT_DEFINITIONS_PATH) / f"{model_type}.yaml"
    with open(yaml_path) as f:
        raw = yaml.safe_load(f)

    return raw.get("beam_mapping", {})


# ---------------------------------------------------------------------------
# Core assembly logic
# ---------------------------------------------------------------------------


def _deterministic_hash_encode(value: str, modulo: int) -> int:
    """Encode a string categorically using deterministic CRC32 hash."""
    return zlib.crc32(value.encode()) % modulo


def assemble_training_data(
    output_path: str,
    source: str = "beam",
    output_format: str = "csv",
    features_path: Optional[str] = None,
    aggregated_path: Optional[str] = None,
    model_type: str = "fraud_detector",
    labeling_strategy: str = "rule_based",
    labeling_kwargs: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """Assemble training data from Beam outputs or Feature Store.

    Args:
        output_path: Destination path (S3 or local) for the training file.
        source: Data source — "beam" (JSON-lines) or "feature_store" (PostgreSQL).
        output_format: Output format — "csv" or "parquet".
        features_path: Path to per-record feature shards (required for source="beam").
        aggregated_path: Path to aggregated feature shards (required for source="beam").
        model_type: Model definition name (loads beam_mapping from config).
        labeling_strategy: Labeling strategy name.
        labeling_kwargs: Extra kwargs for the labeling strategy.

    Returns:
        The assembled DataFrame.
    """
    # Load config
    beam_mapping = _load_beam_mapping(model_type)
    model_def = load_model_definition(model_type)

    if source == "feature_store":
        # Read from PostgreSQL feature store
        import yaml

        from src.models.model_definition import _DEFAULT_DEFINITIONS_PATH

        yaml_path = Path(_DEFAULT_DEFINITIONS_PATH) / f"{model_type}.yaml"
        with open(yaml_path) as f:
            raw = yaml.safe_load(f)

        fs_config = raw.get("feature_store", {})
        feature_groups = fs_config.get(
            "feature_groups", ["transaction_features", "aggregated_features"]
        )
        feature_schema = fs_config.get("schema", {})

        logger.info("Reading features from feature store: groups=%s", feature_groups)
        features_df, aggregated_df = _read_from_feature_store(
            feature_groups, feature_schema
        )
    else:
        # Read from Beam JSON-lines (original path)
        if not features_path or not aggregated_path:
            raise ValueError(
                "--features-path and --aggregated-path are required for source='beam'"
            )

        logger.info("Reading per-record features from %s", features_path)
        features_raw = _read_jsonl(features_path)
        features_df = pd.DataFrame(features_raw)

        logger.info("Reading aggregated features from %s", aggregated_path)
        aggregated_raw = _read_jsonl(aggregated_path)
        aggregated_df = pd.DataFrame(aggregated_raw)

    # Deduplicate per-record features by message_id (skip if all unknown/missing)
    if "message_id" in features_df.columns:
        unique_ids = features_df["message_id"].nunique()
        has_meaningful_ids = unique_ids > 1 or (
            unique_ids == 1 and features_df["message_id"].iloc[0] != "unknown"
        )
        if has_meaningful_ids:
            before = len(features_df)
            features_df = features_df.drop_duplicates(subset=["message_id"])
            dupes = before - len(features_df)
            if dupes > 0:
                logger.info("Dropped %d duplicate records by message_id", dupes)
        else:
            logger.info(
                "Skipping dedup: message_id not set (%d records)", len(features_df)
            )

    # Rename aggregated key column to user_id for join
    if "key" in aggregated_df.columns and "user_id" not in aggregated_df.columns:
        aggregated_df = aggregated_df.rename(columns={"key": "user_id"})

    # Left-join aggregated features to per-record by user_id
    if "user_id" in features_df.columns and "user_id" in aggregated_df.columns:
        # Select only needed aggregated columns to avoid collisions
        agg_columns = ["user_id"]
        agg_field_map = beam_mapping.get("aggregated_fields", {})
        for col_info in agg_field_map.values():
            src = (
                col_info
                if isinstance(col_info, str)
                else col_info.get("source_field", "")
            )
            if src and src in aggregated_df.columns:
                agg_columns.append(src)

        # If no beam_mapping, use common aggregated fields
        if not agg_field_map:
            for col in ["record_count", "avg_amount", "avg_risk_score"]:
                if col in aggregated_df.columns:
                    agg_columns.append(col)

        agg_columns = list(dict.fromkeys(agg_columns))  # dedupe preserving order
        merged_df = features_df.merge(
            aggregated_df[agg_columns], on="user_id", how="left"
        )
        logger.info(
            "Joined %d per-record rows with %d aggregated groups",
            len(features_df),
            len(aggregated_df),
        )
    else:
        logger.warning("Cannot join: user_id missing in one or both DataFrames")
        merged_df = features_df

    # Apply labeling strategy
    labeler = get_labeling_strategy(labeling_strategy, **(labeling_kwargs or {}))
    merged_df["label"] = labeler.assign_labels(merged_df)

    # Map columns per beam_mapping config
    training_df = _map_columns(merged_df, beam_mapping, model_def)

    # Validate
    _validate(training_df, model_def)

    # Write output
    if output_format == "parquet":
        _write_parquet(training_df, output_path)
    else:
        _write_csv(training_df, output_path)

    return training_df


def _map_columns(
    df: pd.DataFrame,
    beam_mapping: Dict[str, Any],
    model_def: Any,
) -> pd.DataFrame:
    """Map Beam feature columns to training columns per config.

    Uses beam_mapping.per_record_fields and beam_mapping.aggregated_fields
    for explicit mappings, plus beam_mapping.transforms for encodings.
    Falls back to direct column matching against model_def.features.columns.
    """
    result: Dict[str, pd.Series] = {}

    per_record = beam_mapping.get("per_record_fields", {})
    agg_fields = beam_mapping.get("aggregated_fields", {})
    transforms = beam_mapping.get("transforms", {})

    all_mappings = {**per_record, **agg_fields}

    for target_col in model_def.features.columns:
        # Check explicit mapping first
        if target_col in all_mappings:
            mapping = all_mappings[target_col]
            source_field = (
                mapping
                if isinstance(mapping, str)
                else mapping.get("source_field", target_col)
            )
            if source_field in df.columns:
                result[target_col] = df[source_field]
            else:
                logger.warning(
                    "Source field '%s' not found for target '%s'",
                    source_field,
                    target_col,
                )
                result[target_col] = 0
        # Check transforms (hash encoding, type casts)
        elif target_col in transforms:
            t = transforms[target_col]
            source_field = t.get("source_field", "")
            transform_type = t.get("type", "")

            if transform_type == "hash_encode" and source_field in df.columns:
                modulo = t.get("modulo", 100)
                result[target_col] = df[source_field].apply(
                    lambda v, m=modulo: _deterministic_hash_encode(str(v), m)
                )
            elif transform_type == "bool_to_int" and source_field in df.columns:
                result[target_col] = df[source_field].astype(int)
            else:
                logger.warning(
                    "Cannot apply transform '%s' for '%s'", transform_type, target_col
                )
                result[target_col] = 0
        # Direct match
        elif target_col in df.columns:
            result[target_col] = df[target_col]
        else:
            logger.warning("No mapping found for training column '%s'", target_col)
            result[target_col] = 0

    # Always include label
    if "label" in df.columns:
        result[model_def.features.target] = df["label"]

    return pd.DataFrame(result)


def _validate(df: pd.DataFrame, model_def: Any) -> None:
    """Validate assembled training data."""
    # Check for expected columns
    expected = set(model_def.features.columns + [model_def.features.target])
    actual = set(df.columns)
    missing = expected - actual
    if missing:
        raise ValueError(f"Missing training columns: {missing}")

    # Null check
    null_counts = df.isnull().sum()
    cols_with_nulls = null_counts[null_counts > 0]
    if not cols_with_nulls.empty:
        logger.warning("Columns with nulls:\n%s", cols_with_nulls.to_string())
        df.fillna(0, inplace=True)
        logger.info("Filled nulls with 0")

    # Class balance check
    if model_def.features.target in df.columns:
        fraud_rate = df[model_def.features.target].mean()
        logger.info(
            "Fraud rate: %.2f%% (%d / %d)",
            fraud_rate * 100,
            df[model_def.features.target].sum(),
            len(df),
        )
        if fraud_rate < 0.01:
            logger.warning(
                "Very low fraud rate (%.2f%%) - model may underperform",
                fraud_rate * 100,
            )
        elif fraud_rate > 0.50:
            logger.warning(
                "Very high fraud rate (%.2f%%) - check labeling strategy",
                fraud_rate * 100,
            )

    # Row count
    if len(df) == 0:
        raise ValueError("Assembled DataFrame is empty - no training data produced")

    logger.info("Validation passed: %d rows, %d columns", len(df), len(df.columns))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assemble training CSV from Beam feature outputs"
    )
    parser.add_argument(
        "--features-path",
        help="Path (S3 or local) to per-record feature shard prefix (required for source=beam)",
    )
    parser.add_argument(
        "--aggregated-path",
        help="Path (S3 or local) to aggregated feature shard prefix (required for source=beam)",
    )
    parser.add_argument(
        "--output-path",
        required=True,
        help="Destination path (S3 or local) for training output",
    )
    parser.add_argument(
        "--source",
        choices=["beam", "feature_store"],
        default="beam",
        help="Data source (default: beam)",
    )
    parser.add_argument(
        "--output-format",
        choices=["csv", "parquet"],
        default="csv",
        help="Output format (default: csv)",
    )
    parser.add_argument(
        "--model-type",
        default="fraud_detector",
        help="Model definition name (default: fraud_detector)",
    )
    parser.add_argument(
        "--labeling-strategy",
        default="rule_based",
        choices=["rule_based", "file_based"],
        help="Labeling strategy (default: rule_based)",
    )
    parser.add_argument(
        "--labels-path",
        help="Path to labels CSV (required for file_based strategy)",
    )
    parser.add_argument(
        "--labeling-threshold",
        type=float,
        default=0.5,
        help="Risk threshold for rule_based labeling (default: 0.5)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    labeling_kwargs: Dict[str, Any] = {}
    if args.labeling_strategy == "rule_based":
        labeling_kwargs["threshold"] = args.labeling_threshold
    elif args.labeling_strategy == "file_based":
        if not args.labels_path:
            parser.error("--labels-path is required for file_based strategy")
        labeling_kwargs["labels_path"] = args.labels_path

    # Validate required args for beam source
    if args.source == "beam" and (not args.features_path or not args.aggregated_path):
        parser.error(
            "--features-path and --aggregated-path are required for source=beam"
        )

    try:
        df = assemble_training_data(
            output_path=args.output_path,
            source=args.source,
            output_format=args.output_format,
            features_path=args.features_path,
            aggregated_path=args.aggregated_path,
            model_type=args.model_type,
            labeling_strategy=args.labeling_strategy,
            labeling_kwargs=labeling_kwargs,
        )
        logger.info(
            "Assembly complete: %d rows written to %s", len(df), args.output_path
        )
    except Exception:
        logger.exception("Assembly failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
