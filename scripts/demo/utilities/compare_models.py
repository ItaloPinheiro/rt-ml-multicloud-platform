#!/usr/bin/env python3
"""
Compare models across experiments and find the best one for production.
"""
import os
from typing import Optional

import mlflow
import pandas as pd

# Set environment variables for MLflow
os.environ["MLFLOW_TRACKING_URI"] = os.getenv(
    "MLFLOW_TRACKING_URI", "http://localhost:5000"
)
os.environ["AWS_ACCESS_KEY_ID"] = "minioadmin"
os.environ["AWS_SECRET_ACCESS_KEY"] = "minioadmin123"
os.environ["MLFLOW_S3_ENDPOINT_URL"] = os.getenv(
    "MLFLOW_S3_ENDPOINT_URL", "http://localhost:9000"
)

mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI"))


def get_experiment_runs(
    experiment_name: str, metric_key: str = "accuracy"
) -> pd.DataFrame:
    """Get all runs from an experiment sorted by metric."""
    client = mlflow.MlflowClient()

    # Get experiment
    experiment = client.get_experiment_by_name(experiment_name)
    if not experiment:
        print(f"Experiment '{experiment_name}' not found")
        return pd.DataFrame()

    # Search runs
    runs = client.search_runs(
        experiment_ids=[experiment.experiment_id],
        order_by=[f"metrics.{metric_key} DESC"],
    )

    # Convert to DataFrame
    runs_data = []
    for run in runs:
        run_data = {
            "run_id": run.info.run_id,
            "experiment_name": experiment_name,
            "status": run.info.status,
            "start_time": run.info.start_time,
        }
        # Add metrics
        for key, value in run.data.metrics.items():
            run_data[f"metric_{key}"] = value
        # Add params
        for key, value in run.data.params.items():
            run_data[f"param_{key}"] = value
        runs_data.append(run_data)

    return pd.DataFrame(runs_data)


def find_best_model_across_experiments(
    experiment_names: list, metric_key: str = "accuracy"
) -> Optional[dict]:
    """Find the best model across multiple experiments."""
    all_runs = []

    for exp_name in experiment_names:
        runs_df = get_experiment_runs(exp_name, metric_key)
        if not runs_df.empty:
            all_runs.append(runs_df)

    if not all_runs:
        print("No runs found in any experiment")
        return None

    # Combine all runs
    combined_df = pd.concat(all_runs, ignore_index=True)

    # Filter successful runs only
    combined_df = combined_df[combined_df["status"] == "FINISHED"]

    if combined_df.empty:
        print("No successful runs found")
        return None

    # Sort by metric
    metric_col = f"metric_{metric_key}"
    if metric_col not in combined_df.columns:
        print(f"Metric '{metric_key}' not found in runs")
        return None

    combined_df = combined_df.sort_values(metric_col, ascending=False)

    # Get best run
    best_run = combined_df.iloc[0]

    return {
        "run_id": best_run["run_id"],
        "experiment_name": best_run["experiment_name"],
        metric_key: best_run[metric_col],
        "all_metrics": {
            col.replace("metric_", ""): best_run[col]
            for col in combined_df.columns
            if col.startswith("metric_")
        },
    }


def promote_best_model(
    model_name: str, experiment_names: list, metric_key: str = "accuracy"
):
    """Find and promote the best model to production."""
    client = mlflow.MlflowClient()

    # Find best model
    best_model = find_best_model_across_experiments(experiment_names, metric_key)

    if not best_model:
        print("No suitable model found")
        return

    print("\nBest model found:")
    print(f"  Run ID: {best_model['run_id']}")
    print(f"  Experiment: {best_model['experiment_name']}")
    print(f"  {metric_key}: {best_model[metric_key]:.4f}")
    print(f"  All metrics: {best_model['all_metrics']}")

    # Register the best model
    try:
        # Create registered model if needed
        try:
            client.create_registered_model(model_name)
            print(f"\nCreated registered model: {model_name}")
        except Exception:
            print(f"\nRegistered model {model_name} already exists")

        # Create model version from best run
        model_version = client.create_model_version(
            name=model_name,
            source=f"runs:/{best_model['run_id']}/model",
            run_id=best_model["run_id"],
        )
        print(f"Created model version: {model_version.version}")

        # Archive previous production models by updating their tags
        all_versions = client.search_model_versions(f"name='{model_name}'")
        for v in all_versions:
            if v.tags.get("deployment_status") == "production":
                client.set_model_version_tag(
                    model_name, v.version, "deployment_status", "archived"
                )
                print(f"Archived previous production model v{v.version}")

        # Promote to production using Alias + Tag (MLflow 2.9+)
        client.set_registered_model_alias(
            model_name, "production", model_version.version
        )
        client.set_model_version_tag(
            model_name, model_version.version, "deployment_status", "production"
        )
        print(f"Promoted model v{model_version.version} to production (alias + tag)")

    except Exception as e:
        print(f"Error promoting model: {e}")


def main():
    """Main function to compare models and promote the best one."""
    print("=" * 60)
    print("Model Comparison and Promotion Tool")
    print("=" * 60)

    # List all experiments
    client = mlflow.MlflowClient()
    experiments = client.search_experiments()

    print("\nAvailable experiments:")
    experiment_names = []
    for exp in experiments:
        if exp.name != "Default":  # Skip default experiment
            print(f"  - {exp.name} (ID: {exp.experiment_id})")
            experiment_names.append(exp.name)

    # Compare models across experiments
    if experiment_names:
        print(
            f"\nSearching for best model across {len(experiment_names)} experiments..."
        )

        # Find and show best models for each experiment
        for exp_name in experiment_names:
            print(f"\n{exp_name}:")
            runs_df = get_experiment_runs(exp_name)
            if not runs_df.empty and "metric_accuracy" in runs_df.columns:
                best_in_exp = runs_df.iloc[0] if len(runs_df) > 0 else None
                if best_in_exp is not None:
                    print(
                        f"  Best accuracy: {best_in_exp.get('metric_accuracy', 0):.4f}"
                    )
                    print(f"  Run ID: {best_in_exp['run_id']}")

        # Find global best
        best_model = find_best_model_across_experiments(experiment_names)
        if best_model:
            print(f"\n{'=' * 40}")
            print("BEST MODEL OVERALL:")
            print(f"  Experiment: {best_model['experiment_name']}")
            print(f"  Accuracy: {best_model['accuracy']:.4f}")
            print(f"  Run ID: {best_model['run_id']}")

            # Ask to promote
            response = input("\nPromote this model to production? (y/n): ")
            if response.lower() == "y":
                model_name = input(
                    "Enter model name (default: fraud_detector): "
                ).strip()
                if not model_name:
                    model_name = "fraud_detector"
                promote_best_model(model_name, experiment_names)
    else:
        print("\nNo experiments found. Train some models first!")


if __name__ == "__main__":
    main()
