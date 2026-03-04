"""
Prepare training-ready CSV from raw transaction data.

Extracts features from raw transaction JSON records using model definitions.
Works with both local files and S3 paths.

Usage:
  # Local files (default: fraud_detector model)
  python -m src.feature_engineering.prepare_training_data \
    --input data/sample/generated/transactions.json \
    --output data/sample/demo/datasets/fraud_detection.csv

  # S3 paths with specific model type
  python -m src.feature_engineering.prepare_training_data \
    --model-type fraud_detector \
    --input s3://bucket/raw/transactions.json \
    --output s3://bucket/datasets/fraud_detection.csv
"""

import argparse
import io
import json
import logging
import sys
import zlib
from typing import Any, Dict, List

import pandas as pd

from src.models.model_definition import load_model_definition

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_feature_columns(model_name: str = "fraud_detector") -> List[str]:
    """Load feature columns (including target) from model definition.

    Args:
        model_name: Model definition name from configs/models/.

    Returns:
        List of feature column names plus the target column.
    """
    model_def = load_model_definition(model_name)
    return model_def.features.columns + [model_def.features.target]


# Default feature columns for backward compatibility
FEATURE_COLUMNS = get_feature_columns("fraud_detector")


def read_data(path: str) -> List[Dict[str, Any]]:
    """Read JSON data from a local file or S3."""
    if path.startswith("s3://"):
        import boto3

        parts = path.replace("s3://", "").split("/", 1)
        bucket, key = parts[0], parts[1]
        s3 = boto3.client("s3")
        response = s3.get_object(Bucket=bucket, Key=key)
        return json.loads(response["Body"].read().decode("utf-8"))
    else:
        with open(path) as f:
            return json.load(f)


def write_csv(df: pd.DataFrame, path: str) -> None:
    """Write DataFrame as CSV to a local file or S3."""
    if path.startswith("s3://"):
        import boto3

        parts = path.replace("s3://", "").split("/", 1)
        bucket, key = parts[0], parts[1]
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        s3 = boto3.client("s3")
        s3.put_object(Bucket=bucket, Key=key, Body=csv_buffer.getvalue())
        logger.info("Written %d rows to %s", len(df), path)
    else:
        import os

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        df.to_csv(path, index=False)
        logger.info("Written %d rows to %s", len(df), path)


def extract_features(transaction: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the 9 training features + label from a raw transaction record.

    Applies the same feature engineering logic as generate_data.py:
    - Temporal features from the pre-computed features dict
    - Amount from the transaction root
    - Categorical encoding via hash
    - Label from the transaction root
    """
    features = transaction.get("features", {})

    return {
        "hour_of_day": features.get("hour_of_day", 0),
        "day_of_week": features.get("day_of_week", 0),
        "is_weekend": int(features.get("is_weekend", False)),
        "transaction_count_24h": features.get("transaction_count_24h", 0),
        "avg_amount_30d": features.get("avg_amount_30d", 0.0),
        "risk_score": features.get("risk_score", 0.0),
        "amount": transaction.get("amount", 0.0),
        "merchant_category_encoded": zlib.crc32(
            transaction.get("merchant_category", "").encode()
        )
        % 100,
        "payment_method_encoded": zlib.crc32(
            transaction.get("payment_method", "").encode()
        )
        % 10,
        "label": transaction.get("label", 0),
    }


def prepare_training_data(
    input_path: str,
    output_path: str,
    feature_columns: List[str] | None = None,
) -> pd.DataFrame:
    """Full pipeline: read raw transactions, extract features, write CSV.

    Args:
        input_path: Path to raw transactions JSON (local or s3://).
        output_path: Path for output training CSV (local or s3://).
        feature_columns: Column names for the output CSV. Defaults to FEATURE_COLUMNS.
    """
    columns = feature_columns or FEATURE_COLUMNS

    logger.info("Reading raw transactions from %s", input_path)
    transactions = read_data(input_path)
    logger.info("Loaded %d raw transactions", len(transactions))

    logger.info("Extracting training features...")
    rows = [extract_features(t) for t in transactions]
    df = pd.DataFrame(rows, columns=columns)

    # Validate no nulls
    null_counts = df.isnull().sum()
    if null_counts.any():
        logger.warning("Null values found:\n%s", null_counts[null_counts > 0])

    # Log target column stats if it exists
    target_col = columns[-1] if columns else "label"
    if target_col in df.columns:
        target_sum = df[target_col].sum()
        target_rate = target_sum / len(df) * 100 if len(df) > 0 else 0
        logger.info(
            "Dataset stats: %d rows, %d positive (%.1f%%), %d features",
            len(df),
            target_sum,
            target_rate,
            len(columns) - 1,
        )
    else:
        logger.info("Dataset stats: %d rows, %d features", len(df), len(columns))

    write_csv(df, output_path)
    return df


def main():
    parser = argparse.ArgumentParser(
        description="Prepare training CSV from raw transaction JSON"
    )
    parser.add_argument(
        "--model-type",
        type=str,
        default="fraud_detector",
        help="Model definition name from configs/models/ (default: fraud_detector)",
    )
    parser.add_argument(
        "--input",
        type=str,
        required=True,
        help="Path to raw transactions JSON (local or s3://)",
    )
    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="Path for output training CSV (local or s3://)",
    )

    args = parser.parse_args()

    # Load feature columns from model definition
    feature_cols = get_feature_columns(args.model_type)

    try:
        prepare_training_data(args.input, args.output, feature_columns=feature_cols)
        logger.info("Feature preparation complete")
    except Exception as e:
        logger.error("Feature preparation failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
