"""Unit tests for feature engineering transforms."""

import importlib.util
import os

import pytest

# apache-beam is an optional dependency (processing group). Load transforms.py
# directly from its file path to avoid the beam package __init__.py which
# imports pipelines.py and fails when beam is not installed.
_spec = importlib.util.spec_from_file_location(
    "transforms",
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "src",
        "feature_engineering",
        "beam",
        "transforms.py",
    ),
)
_transforms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_transforms)
ValidateFeatures = _transforms.ValidateFeatures
load_validation_config = _transforms.load_validation_config


@pytest.fixture
def basic_validation_config():
    """Validation config for testing."""
    return {
        "required_fields": ["amount", "merchant_category", "user_id"],
        "numeric_ranges": {
            "amount": [0, 1000000],
            "hour_of_day": [0, 23],
            "risk_score": [0.0, 1.0],
        },
        "categorical_values": {
            "merchant_category": [
                "electronics",
                "grocery",
                "gas",
                "restaurant",
                "unknown",
            ],
        },
    }


@pytest.fixture
def valid_features():
    """A valid feature record."""
    return {
        "amount": 250.00,
        "merchant_category": "electronics",
        "user_id": "user_123",
        "hour_of_day": 14,
        "risk_score": 0.3,
    }


@pytest.fixture
def validator(basic_validation_config):
    """ValidateFeatures instance with test config."""
    return ValidateFeatures(validation_config=basic_validation_config)


# --- ValidateFeatures tests ---


@pytest.mark.unit
class TestValidateFeatures:
    """Tests for the ValidateFeatures Beam DoFn."""

    def test_valid_record_passes(self, validator, valid_features):
        """Valid records should pass through unchanged."""
        results = list(validator.process(valid_features))
        assert len(results) == 1
        assert results[0] == valid_features

    def test_missing_required_field(self, validator):
        """Records missing required fields should be tagged as invalid."""
        features = {
            "amount": 100.0,
            # missing merchant_category and user_id
        }
        results = list(validator.process(features))
        assert len(results) == 1
        result = results[0]
        assert hasattr(result, "tag")
        assert result.tag == "invalid"
        errors = result.value["validation_errors"]
        missing_fields = [e for e in errors if "Missing required field" in e]
        assert len(missing_fields) == 2

    def test_required_field_with_none_value(self, validator):
        """Required fields set to None should fail validation."""
        features = {
            "amount": 100.0,
            "merchant_category": None,
            "user_id": "user_1",
        }
        results = list(validator.process(features))
        assert len(results) == 1
        result = results[0]
        assert hasattr(result, "tag")
        assert result.tag == "invalid"
        assert any("merchant_category" in e for e in result.value["validation_errors"])

    def test_numeric_out_of_range_below(self, validator, valid_features):
        """Numeric values below the allowed range should fail."""
        valid_features["amount"] = -10.0
        results = list(validator.process(valid_features))
        assert len(results) == 1
        result = results[0]
        assert hasattr(result, "tag")
        assert result.tag == "invalid"
        assert any("amount" in e for e in result.value["validation_errors"])

    def test_numeric_out_of_range_above(self, validator, valid_features):
        """Numeric values above the allowed range should fail."""
        valid_features["risk_score"] = 1.5
        results = list(validator.process(valid_features))
        assert len(results) == 1
        result = results[0]
        assert hasattr(result, "tag")
        assert result.tag == "invalid"
        assert any("risk_score" in e for e in result.value["validation_errors"])

    def test_numeric_at_boundary_values(self, validator, valid_features):
        """Values exactly at range boundaries should pass."""
        valid_features["amount"] = 0
        valid_features["risk_score"] = 1.0
        valid_features["hour_of_day"] = 23
        results = list(validator.process(valid_features))
        assert len(results) == 1
        assert results[0] == valid_features

    def test_invalid_categorical_value(self, validator, valid_features):
        """Categorical values not in allowed set should fail."""
        valid_features["merchant_category"] = "crypto_exchange"
        results = list(validator.process(valid_features))
        assert len(results) == 1
        result = results[0]
        assert hasattr(result, "tag")
        assert result.tag == "invalid"
        assert any("merchant_category" in e for e in result.value["validation_errors"])

    def test_valid_categorical_value(self, validator, valid_features):
        """Categorical values in the allowed set should pass."""
        valid_features["merchant_category"] = "grocery"
        results = list(validator.process(valid_features))
        assert len(results) == 1
        assert results[0] == valid_features

    def test_multiple_validation_errors(self, validator):
        """Records with multiple issues should report all errors."""
        features = {
            "amount": -5.0,
            "merchant_category": "invalid_cat",
            # missing user_id
        }
        results = list(validator.process(features))
        assert len(results) == 1
        result = results[0]
        assert hasattr(result, "tag")
        assert result.tag == "invalid"
        errors = result.value["validation_errors"]
        assert len(errors) >= 3  # missing field + out of range + invalid category

    def test_extra_fields_are_preserved(self, validator, valid_features):
        """Fields not in the validation config should pass through."""
        valid_features["custom_field"] = "extra_data"
        results = list(validator.process(valid_features))
        assert len(results) == 1
        assert results[0]["custom_field"] == "extra_data"

    def test_non_numeric_field_skips_range_check(self, validator, valid_features):
        """Non-numeric values in numeric range fields should skip the range check."""
        valid_features["hour_of_day"] = "not_a_number"
        results = list(validator.process(valid_features))
        assert len(results) == 1
        assert results[0] == valid_features

    def test_empty_config_passes_everything(self, valid_features):
        """Validator with empty config should pass all records."""
        validator = ValidateFeatures(validation_config={})
        results = list(validator.process(valid_features))
        assert len(results) == 1
        assert results[0] == valid_features

    def test_no_config_defaults_to_empty(self):
        """Validator with no config should default to empty rules."""
        validator = ValidateFeatures()
        features = {"any_field": "any_value"}
        results = list(validator.process(features))
        assert len(results) == 1
        assert results[0] == features


# --- load_validation_config tests ---


@pytest.mark.unit
class TestLoadValidationConfig:
    """Tests for the YAML config loader."""

    def test_load_from_yaml_file(self, tmp_path):
        """Should load and parse a valid YAML config."""
        config_file = tmp_path / "validation.yml"
        config_file.write_text(
            "required_fields:\n  - amount\n  - user_id\n"
            "numeric_ranges:\n  amount: [0, 100]\n"
        )
        config = load_validation_config(str(config_file))
        assert config["required_fields"] == ["amount", "user_id"]
        assert config["numeric_ranges"]["amount"] == [0, 100]

    def test_missing_file_returns_empty(self, tmp_path):
        """Should return empty dict when file does not exist."""
        config = load_validation_config(str(tmp_path / "nonexistent.yml"))
        assert config == {}

    def test_empty_file_returns_empty(self, tmp_path):
        """Should return empty dict for an empty YAML file."""
        config_file = tmp_path / "empty.yml"
        config_file.write_text("")
        config = load_validation_config(str(config_file))
        assert config == {}

    def test_validator_from_config_path(self, tmp_path):
        """ValidateFeatures should accept config_path parameter."""
        config_file = tmp_path / "validation.yml"
        config_file.write_text(
            "required_fields:\n  - amount\n" "numeric_ranges:\n  amount: [0, 500]\n"
        )
        validator = ValidateFeatures(config_path=str(config_file))
        assert validator.required_fields == ["amount"]
        assert validator.numeric_ranges == {"amount": [0, 500]}

    def test_validation_config_takes_precedence_over_path(self, tmp_path):
        """Explicit validation_config should override config_path."""
        config_file = tmp_path / "validation.yml"
        config_file.write_text("required_fields:\n  - from_file\n")
        explicit = {"required_fields": ["from_dict"]}
        validator = ValidateFeatures(
            validation_config=explicit, config_path=str(config_file)
        )
        assert validator.required_fields == ["from_dict"]
