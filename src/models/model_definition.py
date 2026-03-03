"""Model definition loader for config-driven model management.

Loads per-model YAML definitions from configs/models/ to drive training,
serving, validation, and feature engineering without hardcoded assumptions.
"""

import importlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# Default path to model definitions directory
_DEFAULT_DEFINITIONS_PATH = os.getenv(
    "MODEL_DEFINITIONS_PATH",
    str(Path(__file__).resolve().parents[2] / "configs" / "models"),
)


@dataclass
class AlgorithmConfig:
    """Algorithm class and default hyperparameters."""

    class_path: str
    default_params: Dict[str, Any] = field(default_factory=dict)

    def create_instance(self, override_params: Optional[Dict[str, Any]] = None) -> Any:
        """Dynamically instantiate the algorithm class.

        Args:
            override_params: Parameters that override defaults.

        Returns:
            An instance of the algorithm class.
        """
        module_path, class_name = self.class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        merged = {**self.default_params, **(override_params or {})}
        return cls(**merged)


@dataclass
class PipelineStepConfig:
    """A preprocessing step in the sklearn Pipeline."""

    name: str
    class_path: str
    params: Dict[str, Any] = field(default_factory=dict)

    def create_instance(self) -> Any:
        """Dynamically instantiate the pipeline step."""
        module_path, class_name = self.class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        return cls(**self.params)


@dataclass
class FeatureConfig:
    """Feature schema for a model."""

    columns: List[str]
    target: str


@dataclass
class MLflowModelConfig:
    """MLflow-specific settings for a model."""

    experiment_name: str


@dataclass
class ServingConfig:
    """Serving-time settings."""

    confidence_threshold: float = 0.5


@dataclass
class ValidationConfig:
    """Validation test input for automated model checks."""

    test_input: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelDefinition:
    """Complete definition of a model type, loaded from YAML config."""

    model_name: str
    display_name: str
    description: str
    task_type: str  # "classification" | "regression"
    algorithm: AlgorithmConfig
    pipeline_steps: List[PipelineStepConfig]
    features: FeatureConfig
    metrics: List[str]
    mlflow: MLflowModelConfig
    serving: ServingConfig
    validation: ValidationConfig


def load_model_definition(
    model_name: str,
    definitions_path: Optional[str] = None,
) -> ModelDefinition:
    """Load a model definition from YAML config.

    Args:
        model_name: Name of the model (matches filename without .yaml).
        definitions_path: Directory containing model YAML files.
            Defaults to configs/models/ relative to project root,
            or MODEL_DEFINITIONS_PATH env var.

    Returns:
        A ModelDefinition instance.

    Raises:
        FileNotFoundError: If the model definition YAML does not exist.
        ValueError: If the YAML is malformed or missing required fields.
    """
    base_path = Path(definitions_path or _DEFAULT_DEFINITIONS_PATH)
    yaml_path = base_path / f"{model_name}.yaml"

    if not yaml_path.exists():
        raise FileNotFoundError(
            f"Model definition not found: {yaml_path}. "
            f"Create {model_name}.yaml in {base_path}/"
        )

    with open(yaml_path, "r") as f:
        raw = yaml.safe_load(f)

    if not raw or not isinstance(raw, dict):
        raise ValueError(f"Invalid model definition in {yaml_path}")

    try:
        algorithm_raw = raw["algorithm"]
        algorithm = AlgorithmConfig(
            class_path=algorithm_raw["class"],
            default_params=algorithm_raw.get("default_params", {}),
        )

        pipeline_steps = [
            PipelineStepConfig(
                name=step["name"],
                class_path=step["class"],
                params=step.get("params", {}),
            )
            for step in raw.get("pipeline_steps", [])
        ]

        features = FeatureConfig(
            columns=raw["features"]["columns"],
            target=raw["features"]["target"],
        )

        mlflow_cfg = MLflowModelConfig(
            experiment_name=raw["mlflow"]["experiment_name"],
        )

        serving_raw = raw.get("serving", {})
        serving = ServingConfig(
            confidence_threshold=serving_raw.get("confidence_threshold", 0.5),
        )

        validation_raw = raw.get("validation", {})
        validation = ValidationConfig(
            test_input=validation_raw.get("test_input", {}),
        )

        return ModelDefinition(
            model_name=raw["model_name"],
            display_name=raw.get("display_name", raw["model_name"]),
            description=raw.get("description", ""),
            task_type=raw["task_type"],
            algorithm=algorithm,
            pipeline_steps=pipeline_steps,
            features=features,
            metrics=raw.get("metrics", []),
            mlflow=mlflow_cfg,
            serving=serving,
            validation=validation,
        )
    except KeyError as e:
        raise ValueError(
            f"Missing required field {e} in model definition {yaml_path}"
        ) from e


def list_model_definitions(
    definitions_path: Optional[str] = None,
) -> List[str]:
    """List available model definition names.

    Args:
        definitions_path: Directory containing model YAML files.

    Returns:
        List of model names (without .yaml extension).
    """
    base_path = Path(definitions_path or _DEFAULT_DEFINITIONS_PATH)
    if not base_path.exists():
        return []
    return sorted(p.stem for p in base_path.glob("*.yaml"))
