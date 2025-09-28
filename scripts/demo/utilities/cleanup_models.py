#!/usr/bin/env python3
"""
Script to clean up all models and experiments in MLflow.
USE WITH CAUTION - This will delete all models and optionally all experiments!
"""
import os
import sys
import mlflow
from mlflow.tracking import MlflowClient
import argparse
import time

def confirm_deletion(message):
    """Ask user for confirmation."""
    print(f"\n{message}")
    response = input("Type 'YES' to confirm, or anything else to cancel: ")
    return response == "YES"

def cleanup_models(
    delete_models=True,
    delete_experiments=False,
    keep_experiments=None,
    keep_models=None,
    force=False
):
    """
    Clean up MLflow models and optionally experiments.

    Args:
        delete_models: Delete all registered models
        delete_experiments: Delete all experiments (except Default)
        keep_experiments: List of experiment names to keep
        keep_models: List of model names to keep
        force: Skip confirmation prompts
    """
    # Set MLflow tracking URI
    mlflow_uri = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
    print(f"Connecting to MLflow at: {mlflow_uri}")
    print("=" * 80)

    mlflow.set_tracking_uri(mlflow_uri)
    client = MlflowClient()

    keep_experiments = keep_experiments or []
    keep_models = keep_models or []

    try:
        # Clean up registered models
        if delete_models:
            models = client.search_registered_models()
            models_to_delete = [m for m in models if m.name not in keep_models]

            if models_to_delete:
                print(f"\nFound {len(models_to_delete)} model(s) to delete:")
                for model in models_to_delete:
                    versions = client.search_model_versions(f"name='{model.name}'")
                    print(f"  - {model.name} ({len(versions)} versions)")

                if force or confirm_deletion("Delete all these models and their versions?"):
                    for model in models_to_delete:
                        print(f"\nDeleting model: {model.name}")

                        # First, delete all versions
                        versions = client.search_model_versions(f"name='{model.name}'")
                        for version in versions:
                            print(f"  Deleting version {version.version}...")
                            client.delete_model_version(
                                name=model.name,
                                version=version.version
                            )
                            time.sleep(0.1)  # Small delay to avoid overwhelming the server

                        # Then delete the registered model
                        print(f"  Deleting model registry entry...")
                        client.delete_registered_model(model.name)
                        print(f"  Model {model.name} deleted successfully")

                    print(f"\nDeleted {len(models_to_delete)} model(s)")
                else:
                    print("Model deletion cancelled")
            else:
                print("No models to delete")

        # Clean up experiments
        if delete_experiments:
            experiments = client.search_experiments()
            # Never delete the Default experiment (ID: 0)
            experiments_to_delete = [
                e for e in experiments
                if e.name not in keep_experiments
                and e.name != "Default"
                and e.experiment_id != "0"
                and e.lifecycle_stage == "active"
            ]

            if experiments_to_delete:
                print(f"\nFound {len(experiments_to_delete)} experiment(s) to delete:")
                for exp in experiments_to_delete:
                    # Count runs in this experiment
                    runs = client.search_runs(experiment_ids=[exp.experiment_id])
                    print(f"  - {exp.name} (ID: {exp.experiment_id}, Runs: {len(runs)})")

                if force or confirm_deletion("Delete all these experiments and their runs?"):
                    for exp in experiments_to_delete:
                        print(f"\nDeleting experiment: {exp.name} (ID: {exp.experiment_id})")

                        # Delete all runs in the experiment
                        runs = client.search_runs(experiment_ids=[exp.experiment_id])
                        for run in runs:
                            print(f"  Deleting run {run.info.run_id[:8]}...")
                            client.delete_run(run.info.run_id)
                            time.sleep(0.05)

                        # Delete the experiment
                        print(f"  Deleting experiment...")
                        client.delete_experiment(exp.experiment_id)
                        print(f"  Experiment {exp.name} deleted successfully")

                    print(f"\nDeleted {len(experiments_to_delete)} experiment(s)")
                else:
                    print("Experiment deletion cancelled")
            else:
                print("No experiments to delete (keeping Default)")

        # Clean up artifacts from MinIO if configured
        if os.getenv("MLFLOW_S3_ENDPOINT_URL"):
            print("\n" + "=" * 80)
            print("ARTIFACT CLEANUP")
            print("=" * 80)
            print("Note: Artifacts in S3/MinIO may need manual cleanup.")
            print("To clean MinIO artifacts, run:")
            print("  docker exec ml-mlflow-minio mc rm -r --force local/mlflow/")
            print("  docker exec ml-mlflow-minio mc mb local/mlflow")

        print("\n" + "=" * 80)
        print("CLEANUP COMPLETE")
        print("=" * 80)

        # Show remaining items
        remaining_models = client.search_registered_models()
        remaining_experiments = [e for e in client.search_experiments() if e.lifecycle_stage == "active"]

        print(f"Remaining models: {len(remaining_models)}")
        print(f"Remaining experiments: {len(remaining_experiments)}")

    except Exception as e:
        print(f"Error during cleanup: {e}")
        return 1

    return 0

def main():
    parser = argparse.ArgumentParser(description="Clean up MLflow models and experiments")
    parser.add_argument(
        "--models",
        action="store_true",
        help="Delete all registered models"
    )
    parser.add_argument(
        "--experiments",
        action="store_true",
        help="Delete all experiments (except Default)"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Delete both models and experiments"
    )
    parser.add_argument(
        "--keep-models",
        nargs="+",
        help="List of model names to keep"
    )
    parser.add_argument(
        "--keep-experiments",
        nargs="+",
        help="List of experiment names to keep"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompts (use with caution!)"
    )
    parser.add_argument(
        "--mlflow-uri",
        help="MLflow tracking URI (default: http://localhost:5000)"
    )

    args = parser.parse_args()

    if args.mlflow_uri:
        os.environ["MLFLOW_TRACKING_URI"] = args.mlflow_uri

    if not (args.models or args.experiments or args.all):
        print("Error: Specify --models, --experiments, or --all")
        parser.print_help()
        return 1

    delete_models = args.models or args.all
    delete_experiments = args.experiments or args.all

    return cleanup_models(
        delete_models=delete_models,
        delete_experiments=delete_experiments,
        keep_experiments=args.keep_experiments,
        keep_models=args.keep_models,
        force=args.force
    )

if __name__ == "__main__":
    sys.exit(main())