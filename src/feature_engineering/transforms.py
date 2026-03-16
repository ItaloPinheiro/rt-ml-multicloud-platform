"""Shared model-dependent feature transformations.

Single source of truth for transforms applied at both training time
(assemble_training_data, prepare_training_data) and serving time (API).

These are *model-dependent* transforms (encoding, type coercion) that sit
between the Feature Store (model-independent features) and the model.
See: Hopsworks "model-dependent transformations applied at retrieval".
"""

import zlib
from typing import Any, Dict, Optional


def hash_encode(value: str, modulo: int = 100) -> int:
    """Deterministic categorical encoding via CRC32 hash.

    Consistent across training and serving — same input always produces
    the same integer bucket.
    """
    return zlib.crc32(value.encode()) % modulo


def bool_to_int(value: Any) -> int:
    """Convert a boolean-like value to 0/1 integer.

    Handles bool, str ("true"/"false"/"1"/"0"), int, and None.
    """
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(bool(value))
    if isinstance(value, str):
        return int(value.lower() in ("true", "1", "yes"))
    return 0


def coerce_numeric(value: Any) -> Any:
    """Coerce a value to its natural numeric type (int or float).

    Used when mapping raw Feature Store values to model input fields.
    Preserves int for integers, float for decimals.
    """
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    try:
        f = float(value)
        return int(f) if f == int(f) else f
    except (TypeError, ValueError):
        return 0


def apply_transform(
    transform_type: str,
    raw_value: Any,
    modulo: int = 100,
) -> Any:
    """Apply a named transform to a raw feature value.

    Dispatches to hash_encode or bool_to_int based on transform_type.
    Used by both training assembly and API serving paths.
    """
    if transform_type == "hash_encode" and raw_value is not None:
        return hash_encode(str(raw_value), modulo)
    elif transform_type == "bool_to_int":
        return bool_to_int(raw_value)
    return 0


def transform_features(
    raw_features: Dict[str, Any],
    beam_mapping: Dict[str, Any],
    expected_columns: list,
) -> Dict[str, Any]:
    """Transform raw Feature Store features to model-ready features.

    Applies the beam_mapping config (per_record_fields, aggregated_fields,
    transforms) to produce exactly the columns the model expects.

    This function is used by both:
    - API serving: _transform_features_for_model() in main.py
    - Training assembly: _map_columns() in assemble_training_data.py (single-row)

    Args:
        raw_features: Dict of raw feature values keyed by feature name.
        beam_mapping: The beam_mapping section from the model config YAML.
        expected_columns: List of column names the model expects.

    Returns:
        Dict with exactly the expected_columns as keys, values transformed.
    """
    per_record = beam_mapping.get("per_record_fields", {})
    agg_fields = beam_mapping.get("aggregated_fields", {})
    transforms = beam_mapping.get("transforms", {})

    result: Dict[str, Any] = {}
    all_mappings = {**per_record, **agg_fields}

    for target_col in expected_columns:
        # Explicit mapping (per-record or aggregated)
        if target_col in all_mappings:
            mapping = all_mappings[target_col]
            source_field = (
                mapping
                if isinstance(mapping, str)
                else mapping.get("source_field", target_col)
            )
            val = raw_features.get(source_field, 0)
            result[target_col] = coerce_numeric(val)

        # Transforms (hash encoding, bool_to_int)
        elif target_col in transforms:
            t = transforms[target_col]
            source_field = t.get("source_field", "")
            transform_type = t.get("type", "")
            raw_val = raw_features.get(source_field)
            modulo = t.get("modulo", 100)
            result[target_col] = apply_transform(transform_type, raw_val, modulo)

        # Direct match
        elif target_col in raw_features:
            result[target_col] = coerce_numeric(raw_features[target_col])

        else:
            result[target_col] = 0

    return result


def load_beam_mapping(model_name: str) -> Optional[Dict[str, Any]]:
    """Load beam_mapping config from a model definition YAML.

    Shared helper so that both API and training code load the same config.
    Returns None if the config file or beam_mapping section doesn't exist.
    """
    import os

    import yaml

    config_path = os.path.join("configs", "models", f"{model_name}.yaml")
    if not os.path.exists(config_path):
        return None
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    return raw.get("beam_mapping")
