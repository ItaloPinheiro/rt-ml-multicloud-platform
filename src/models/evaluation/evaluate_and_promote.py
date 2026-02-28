"""
Model evaluation gate: compares the latest trained model against the current
production champion and promotes only if the challenger wins.

Promotion criteria:
  - accuracy >= champion accuracy (no regression)
  - accuracy >= minimum threshold (configurable, default 0.80)
  - f1_score >= champion f1_score (balanced performance)

If no champion exists yet (first model), promotes unconditionally as long as
the minimum accuracy threshold is met.

Usage:
  python -m src.models.evaluation.evaluate_and_promote \
    --mlflow-uri http://mlflow-service:5000 \
    --model-name fraud_detector \
    --min-accuracy 0.80
"""

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from typing import Dict, Optional

import mlflow

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@dataclass
class ModelMetrics:
    """Metrics for a model version."""

    version: str
    run_id: str
    accuracy: float
    f1_score: float
    precision: float
    recall: float


def get_model_metrics(
    client: mlflow.MlflowClient, model_name: str, version: str
) -> Optional[ModelMetrics]:
    """Fetch metrics for a specific model version from its MLflow run."""
    try:
        model_version = client.get_model_version(model_name, version)
        run = client.get_run(model_version.run_id)
        metrics = run.data.metrics

        return ModelMetrics(
            version=version,
            run_id=model_version.run_id,
            accuracy=metrics.get("accuracy", 0.0),
            f1_score=metrics.get("f1_score", 0.0),
            precision=metrics.get("precision", 0.0),
            recall=metrics.get("recall", 0.0),
        )
    except Exception as e:
        logger.error(
            "Failed to fetch metrics for model %s v%s: %s", model_name, version, e
        )
        return None


def get_champion_version(client: mlflow.MlflowClient, model_name: str) -> Optional[str]:
    """Get the current production champion version via alias or tag."""
    # Try alias first (MLflow 2.9+)
    try:
        model_version = client.get_model_version_by_alias(model_name, "production")
        return model_version.version
    except Exception:
        pass

    # Fallback: search by deployment_status tag
    try:
        versions = client.search_model_versions(f"name='{model_name}'")
        for v in versions:
            if v.tags.get("deployment_status") == "production":
                return v.version
    except Exception as e:
        logger.debug("Tag-based champion search failed: %s", e)

    return None


def get_latest_version(client: mlflow.MlflowClient, model_name: str) -> Optional[str]:
    """Get the most recently registered model version."""
    try:
        versions = client.search_model_versions(f"name='{model_name}'")
        if not versions:
            return None
        # Sort by version number descending (versions are strings)
        sorted_versions = sorted(versions, key=lambda v: int(v.version), reverse=True)
        return sorted_versions[0].version
    except Exception as e:
        logger.error("Failed to get latest version for %s: %s", model_name, e)
        return None


def promote_model(client: mlflow.MlflowClient, model_name: str, version: str) -> bool:
    """Promote a model version to production via alias and tag."""
    try:
        # Set alias (MLflow 2.9+)
        try:
            client.set_registered_model_alias(
                name=model_name,
                alias="production",
                version=version,
            )
            logger.info("Set 'production' alias on %s v%s", model_name, version)
        except (AttributeError, Exception) as e:
            logger.debug("Alias API not available: %s", e)

        # Set deployment_status tag on new version
        client.set_model_version_tag(
            name=model_name,
            version=version,
            key="deployment_status",
            value="production",
        )

        # Archive previous production versions
        all_versions = client.search_model_versions(f"name='{model_name}'")
        for v in all_versions:
            if v.version != version and v.tags.get("deployment_status") == "production":
                client.set_model_version_tag(
                    name=model_name,
                    version=v.version,
                    key="deployment_status",
                    value="archived",
                )
                logger.info("Archived previous champion v%s", v.version)

        return True
    except Exception as e:
        logger.error("Failed to promote model %s v%s: %s", model_name, version, e)
        return False


def evaluate_and_promote(
    mlflow_uri: str,
    model_name: str,
    min_accuracy: float = 0.80,
) -> Dict:
    """
    Compare the latest model version against the current champion.
    Promote if the challenger is better.

    Returns a dict with the evaluation result and decision.
    """
    mlflow.set_tracking_uri(mlflow_uri)
    client = mlflow.MlflowClient()

    result = {
        "model_name": model_name,
        "decision": "rejected",
        "reason": "",
        "champion": None,
        "challenger": None,
    }

    # Get the latest (challenger) version
    latest_version = get_latest_version(client, model_name)
    if not latest_version:
        result["reason"] = "No model versions found"
        logger.error(result["reason"])
        return result

    challenger = get_model_metrics(client, model_name, latest_version)
    if not challenger:
        result["reason"] = f"Could not fetch metrics for challenger v{latest_version}"
        logger.error(result["reason"])
        return result

    result["challenger"] = {
        "version": challenger.version,
        "accuracy": challenger.accuracy,
        "f1_score": challenger.f1_score,
        "precision": challenger.precision,
        "recall": challenger.recall,
    }

    logger.info(
        "Challenger v%s - accuracy: %.4f, f1: %.4f, precision: %.4f, recall: %.4f",
        challenger.version,
        challenger.accuracy,
        challenger.f1_score,
        challenger.precision,
        challenger.recall,
    )

    # Check minimum accuracy threshold
    if challenger.accuracy < min_accuracy:
        result["reason"] = (
            f"Challenger accuracy {challenger.accuracy:.4f} below "
            f"minimum threshold {min_accuracy:.4f}"
        )
        logger.warning(result["reason"])
        return result

    # Get the current champion
    champion_version = get_champion_version(client, model_name)

    if not champion_version:
        # No champion yet - promote the first model
        logger.info(
            "No existing champion found. Promoting challenger v%s as first champion",
            challenger.version,
        )
        if promote_model(client, model_name, challenger.version):
            result["decision"] = "promoted"
            result["reason"] = "First model promoted (no existing champion)"
        else:
            result["reason"] = "Promotion failed"
        return result

    if champion_version == latest_version:
        result["decision"] = "skipped"
        result["reason"] = "Latest version is already the champion"
        logger.info(result["reason"])
        return result

    champion = get_model_metrics(client, model_name, champion_version)
    if not champion:
        result["reason"] = f"Could not fetch metrics for champion v{champion_version}"
        logger.error(result["reason"])
        return result

    result["champion"] = {
        "version": champion.version,
        "accuracy": champion.accuracy,
        "f1_score": champion.f1_score,
        "precision": champion.precision,
        "recall": champion.recall,
    }

    logger.info(
        "Champion v%s - accuracy: %.4f, f1: %.4f, precision: %.4f, recall: %.4f",
        champion.version,
        champion.accuracy,
        champion.f1_score,
        champion.precision,
        champion.recall,
    )

    # Compare: challenger must be >= champion on both accuracy and f1
    accuracy_ok = challenger.accuracy >= champion.accuracy
    f1_ok = challenger.f1_score >= champion.f1_score

    if accuracy_ok and f1_ok:
        logger.info(
            "Challenger v%s beats champion v%s (accuracy: %.4f >= %.4f, f1: %.4f >= %.4f)",
            challenger.version,
            champion.version,
            challenger.accuracy,
            champion.accuracy,
            challenger.f1_score,
            champion.f1_score,
        )
        if promote_model(client, model_name, challenger.version):
            result["decision"] = "promoted"
            result["reason"] = (
                f"Challenger v{challenger.version} promoted over champion v{champion.version}"
            )
        else:
            result["reason"] = "Promotion failed"
    else:
        reasons = []
        if not accuracy_ok:
            reasons.append(
                f"accuracy {challenger.accuracy:.4f} < {champion.accuracy:.4f}"
            )
        if not f1_ok:
            reasons.append(
                f"f1_score {challenger.f1_score:.4f} < {champion.f1_score:.4f}"
            )
        result["reason"] = (
            f"Challenger v{challenger.version} rejected: {', '.join(reasons)}"
        )
        logger.warning(result["reason"])

    return result


def main():
    """CLI entry point for the evaluation gate."""
    parser = argparse.ArgumentParser(
        description="Evaluate latest model against production champion"
    )
    parser.add_argument(
        "--mlflow-uri",
        type=str,
        default=os.getenv("MLFLOW_TRACKING_URI", "http://mlflow-service:5000"),
        help="MLflow tracking URI",
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default="fraud_detector",
        help="Registered model name to evaluate",
    )
    parser.add_argument(
        "--min-accuracy",
        type=float,
        default=0.80,
        help="Minimum accuracy threshold for promotion",
    )

    args = parser.parse_args()

    logger.info("=== Model Evaluation Gate ===")
    logger.info("MLflow URI: %s", args.mlflow_uri)
    logger.info("Model: %s", args.model_name)
    logger.info("Min accuracy threshold: %.2f", args.min_accuracy)

    result = evaluate_and_promote(
        mlflow_uri=args.mlflow_uri,
        model_name=args.model_name,
        min_accuracy=args.min_accuracy,
    )

    logger.info("=== Evaluation Result ===")
    logger.info("Decision: %s", result["decision"])
    logger.info("Reason: %s", result["reason"])

    if result["champion"]:
        logger.info(
            "Champion: v%s (accuracy=%.4f, f1=%.4f)",
            result["champion"]["version"],
            result["champion"]["accuracy"],
            result["champion"]["f1_score"],
        )

    if result["challenger"]:
        logger.info(
            "Challenger: v%s (accuracy=%.4f, f1=%.4f)",
            result["challenger"]["version"],
            result["challenger"]["accuracy"],
            result["challenger"]["f1_score"],
        )

    # Exit with non-zero if rejected (useful for CI/CD pipelines)
    if result["decision"] == "rejected":
        sys.exit(1)


if __name__ == "__main__":
    main()
