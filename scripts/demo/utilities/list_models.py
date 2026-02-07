#!/usr/bin/env python3
"""
Script to list all models in MLflow registry with detailed information.
"""
import os
import sys
from datetime import datetime

import mlflow
from mlflow.tracking import MlflowClient

try:
    from tabulate import tabulate

    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False


def format_timestamp(timestamp_ms):
    """Convert timestamp to readable format."""
    if timestamp_ms:
        return datetime.fromtimestamp(timestamp_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
    return "N/A"


def list_models():
    """List all registered models with their versions and details."""
    # Set MLflow tracking URI
    mlflow_uri = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
    print(f"Connecting to MLflow at: {mlflow_uri}")
    print("=" * 80)

    mlflow.set_tracking_uri(mlflow_uri)
    client = MlflowClient()

    try:
        # Get all registered models
        models = client.search_registered_models()

        if not models:
            print("No registered models found.")
            return

        print(f"Found {len(models)} registered model(s):\n")

        for model in models:
            print(f"\nModel: {model.name}")
            print("-" * 40)
            print(f"Created: {format_timestamp(model.creation_timestamp)}")
            print(f"Updated: {format_timestamp(model.last_updated_timestamp)}")
            print(f"Description: {model.description or 'No description'}")

            # Get all versions for this model
            versions = client.search_model_versions(f"name='{model.name}'")

            if versions:
                # Prepare version data for table
                version_data = []
                for v in sorted(versions, key=lambda x: int(x.version), reverse=True):
                    version_data.append(
                        [
                            v.version,
                            v.current_stage,
                            v.status,
                            format_timestamp(v.creation_timestamp),
                            v.run_id[:8] if v.run_id else "N/A",
                            v.source[:50] + "..." if len(v.source) > 50 else v.source,
                        ]
                    )

                print(f"\nVersions ({len(versions)} total):")
                headers = ["Version", "Stage", "Status", "Created", "Run ID", "Source"]
                if HAS_TABULATE:
                    print(tabulate(version_data, headers=headers, tablefmt="grid"))
                else:
                    # Simple table without tabulate
                    print(
                        f"{'Version':<8} {'Stage':<12} {'Status':<8} {'Created':<20} {'Run ID':<10} {'Source':<30}"
                    )
                    print("-" * 90)
                    for row in version_data:
                        print(
                            f"{row[0]:<8} {row[1]:<12} {row[2]:<8} {row[3]:<20} {row[4]:<10} {row[5]:<30}"
                        )
            else:
                print("No versions found for this model.")

            print("")

        # Summary statistics
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)

        total_models = len(models)
        total_versions = sum(
            len(client.search_model_versions(f"name='{m.name}'")) for m in models
        )

        # Count versions by stage
        stage_counts = {"Production": 0, "Staging": 0, "Archived": 0, "None": 0}
        for model in models:
            versions = client.search_model_versions(f"name='{model.name}'")
            for v in versions:
                stage_counts[v.current_stage] = stage_counts.get(v.current_stage, 0) + 1

        print(f"Total Models: {total_models}")
        print(f"Total Versions: {total_versions}")
        print("\nVersions by Stage:")
        for stage, count in stage_counts.items():
            if count > 0:
                print(f"  {stage}: {count}")

        # List experiments
        print("\n" + "=" * 80)
        print("EXPERIMENTS")
        print("=" * 80)

        experiments = client.search_experiments()
        exp_data = []
        for exp in experiments:
            if exp.lifecycle_stage == "active":
                exp_data.append(
                    [
                        exp.experiment_id,
                        exp.name,
                        (
                            exp.artifact_location[:50] + "..."
                            if len(exp.artifact_location) > 50
                            else exp.artifact_location
                        ),
                    ]
                )

        if exp_data:
            headers = ["ID", "Name", "Artifact Location"]
            if HAS_TABULATE:
                print(tabulate(exp_data, headers=headers, tablefmt="grid"))
            else:
                print(f"{'ID':<5} {'Name':<30} {'Artifact Location':<50}")
                print("-" * 85)
                for row in exp_data:
                    print(f"{row[0]:<5} {row[1]:<30} {row[2]:<50}")

    except Exception as e:
        print(f"Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(list_models())
