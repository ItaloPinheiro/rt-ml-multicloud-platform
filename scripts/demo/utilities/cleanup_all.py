#!/usr/bin/env python3
"""
Complete cleanup script for MLflow models, experiments, and MinIO/S3 artifacts.
USE WITH CAUTION - This will delete all data!
"""
import argparse
import os
import sys
import time

import boto3
import mlflow
from botocore.client import Config
from mlflow.tracking import MlflowClient


def confirm_deletion(message):
    """Ask user for confirmation."""
    print(f"\n{message}")
    response = input("Type 'YES' to confirm, or anything else to cancel: ")
    return response == "YES"


def cleanup_minio_artifacts(force=False):
    """Clean up all artifacts in MinIO/S3."""
    try:
        # Get MinIO configuration
        endpoint_url = os.getenv("MLFLOW_S3_ENDPOINT_URL", "http://localhost:9000")
        access_key = os.getenv("AWS_ACCESS_KEY_ID", "minioadmin")
        secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", "minioadmin123")
        bucket_name = "mlflow"

        print("\n" + "=" * 80)
        print("MINIO/S3 ARTIFACT CLEANUP")
        print("=" * 80)
        print(f"Endpoint: {endpoint_url}")
        print(f"Bucket: {bucket_name}")

        # Create S3 client
        s3_client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )

        # List all objects in the bucket
        try:
            response = s3_client.list_objects_v2(Bucket=bucket_name)

            if "Contents" in response:
                objects = response["Contents"]
                total_size = sum(obj["Size"] for obj in objects)

                print(f"\nFound {len(objects)} objects in bucket")
                print(f"Total size: {total_size / (1024*1024):.2f} MB")

                if force or confirm_deletion(
                    f"Delete all {len(objects)} objects from MinIO?"
                ):
                    # Delete objects in batches
                    batch_size = 1000
                    deleted_count = 0

                    while True:
                        response = s3_client.list_objects_v2(
                            Bucket=bucket_name, MaxKeys=batch_size
                        )

                        if "Contents" not in response:
                            break

                        objects = response["Contents"]
                        if not objects:
                            break

                        # Prepare delete request
                        delete_objects = {
                            "Objects": [{"Key": obj["Key"]} for obj in objects]
                        }

                        print(f"  Deleting batch of {len(objects)} objects...")
                        s3_client.delete_objects(
                            Bucket=bucket_name, Delete=delete_objects
                        )
                        deleted_count += len(objects)

                        if not response.get("IsTruncated"):
                            break

                    print(f"Deleted {deleted_count} objects from MinIO")
                else:
                    print("MinIO cleanup cancelled")
            else:
                print("No objects found in MinIO bucket")

        except Exception as e:
            if "NoSuchBucket" in str(e):
                print(f"Bucket '{bucket_name}' does not exist")
            else:
                print(f"Error accessing MinIO: {e}")

    except Exception as e:
        print(f"Error setting up MinIO client: {e}")
        print("\nAlternative: Run these commands manually:")
        print("  docker exec ml-mlflow-minio mc rm -r --force local/mlflow/")
        print("  docker exec ml-mlflow-minio mc mb local/mlflow")


def cleanup_database_directly(force=False):
    """Clean up MLflow database tables directly."""
    import os
    import subprocess
    import tempfile

    print("\n" + "=" * 80)
    print("DATABASE CLEANUP")
    print("=" * 80)

    if force or confirm_deletion(
        "Permanently delete ALL experiments from database (including deleted ones)?"
    ):
        try:
            # Create SQL script for comprehensive cleanup
            cleanup_sql = """
-- Delete all data related to deleted experiments
BEGIN;

-- Get deleted experiment IDs
CREATE TEMP TABLE IF NOT EXISTS deleted_exp_ids AS
SELECT experiment_id FROM experiments WHERE lifecycle_stage = 'deleted';

-- Get run UUIDs from deleted experiments
CREATE TEMP TABLE IF NOT EXISTS deleted_run_uuids AS
SELECT run_uuid FROM runs WHERE experiment_id IN (SELECT experiment_id FROM deleted_exp_ids);

-- Delete from all dependent tables in order
DELETE FROM logged_model_metrics WHERE experiment_id IN (SELECT experiment_id FROM deleted_exp_ids);
DELETE FROM logged_model_params WHERE experiment_id IN (SELECT experiment_id FROM deleted_exp_ids);
DELETE FROM logged_model_tags WHERE experiment_id IN (SELECT experiment_id FROM deleted_exp_ids);
DELETE FROM logged_models WHERE experiment_id IN (SELECT experiment_id FROM deleted_exp_ids);
DELETE FROM tags WHERE run_uuid IN (SELECT run_uuid FROM deleted_run_uuids);
DELETE FROM metrics WHERE run_uuid IN (SELECT run_uuid FROM deleted_run_uuids);
DELETE FROM params WHERE run_uuid IN (SELECT run_uuid FROM deleted_run_uuids);
DELETE FROM latest_metrics WHERE run_uuid IN (SELECT run_uuid FROM deleted_run_uuids);
DELETE FROM runs WHERE experiment_id IN (SELECT experiment_id FROM deleted_exp_ids);
DELETE FROM experiment_tags WHERE experiment_id IN (SELECT experiment_id FROM deleted_exp_ids);
DELETE FROM experiments WHERE experiment_id IN (SELECT experiment_id FROM deleted_exp_ids);

DROP TABLE IF EXISTS deleted_run_uuids;
DROP TABLE IF EXISTS deleted_exp_ids;

COMMIT;
"""

            # Write SQL to temp file
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".sql", delete=False
            ) as f:
                f.write(cleanup_sql)
                temp_sql_file = f.name

            try:
                # Execute SQL script via docker
                if os.name == "nt":  # Windows
                    # Use type command on Windows
                    cmd = f'type "{temp_sql_file}" | docker exec -i ml-mlflow-db psql -U mlflow -d mlflow'
                    result = subprocess.run(
                        cmd, shell=True, capture_output=True, text=True
                    )
                else:
                    # Use cat on Unix-like systems
                    cmd = f'cat "{temp_sql_file}" | docker exec -i ml-mlflow-db psql -U mlflow -d mlflow'
                    result = subprocess.run(
                        cmd, shell=True, capture_output=True, text=True
                    )

                if result.returncode == 0:
                    print("Successfully cleaned deleted experiments from database")
                    # Parse output to show what was deleted
                    output_lines = result.stdout.strip().split("\n")
                    for line in output_lines:
                        if line.startswith("DELETE"):
                            print(f"  {line}")
                else:
                    print(f"Error cleaning database: {result.stderr}")

            finally:
                # Clean up temp file
                try:
                    os.unlink(temp_sql_file)
                except Exception:
                    pass

        except Exception as e:
            print(f"Error during database cleanup: {e}")
            print("\nManual cleanup commands:")
            print(
                "  docker exec ml-mlflow-db psql -U mlflow -d mlflow -c \"DELETE FROM experiments WHERE lifecycle_stage = 'deleted';\""
            )
            print("\nFor complete reset:")
            print(
                "  docker exec ml-mlflow-db psql -U mlflow -d mlflow -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'"
            )
            print(
                "  docker-compose -f ops/local/docker-compose.yml -f ops/local/docker-compose.override.yml restart mlflow-server"
            )
    else:
        print("Database cleanup cancelled")


def cleanup_mlflow(
    delete_models=True,
    delete_experiments=False,
    delete_artifacts=False,
    keep_experiments=None,
    keep_models=None,
    force=False,
):
    """
    Complete cleanup of MLflow models, experiments, and artifacts.
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
        # Step 1: Clean up registered models
        if delete_models:
            print("\n" + "=" * 80)
            print("MODEL CLEANUP")
            print("=" * 80)

            models = client.search_registered_models()
            models_to_delete = [m for m in models if m.name not in keep_models]

            if models_to_delete:
                print(f"Found {len(models_to_delete)} model(s) to delete:")
                for model in models_to_delete:
                    versions = client.search_model_versions(f"name='{model.name}'")
                    print(f"  - {model.name} ({len(versions)} versions)")

                if force or confirm_deletion(
                    "Delete all these models and their versions?"
                ):
                    for model in models_to_delete:
                        print(f"\nDeleting model: {model.name}")

                        # Delete all versions
                        versions = client.search_model_versions(f"name='{model.name}'")
                        for version in versions:
                            print(f"  Deleting version {version.version}...")
                            try:
                                # No need to transition stages as they're deprecated
                                # Just delete the version directly
                                client.delete_model_version(
                                    name=model.name, version=version.version
                                )
                            except Exception as e:
                                print(f"    Warning: {e}")
                            time.sleep(0.1)

                        # Delete the registered model
                        print("  Deleting model registry entry...")
                        client.delete_registered_model(model.name)
                        print(f"  Model {model.name} deleted successfully")

                    print(f"\nDeleted {len(models_to_delete)} model(s)")
                else:
                    print("Model deletion cancelled")
            else:
                print("No models to delete")

        # Step 2: Clean up experiments
        if delete_experiments:
            print("\n" + "=" * 80)
            print("EXPERIMENT CLEANUP")
            print("=" * 80)

            experiments = client.search_experiments()
            experiments_to_delete = [
                e
                for e in experiments
                if e.name not in keep_experiments
                and e.name != "Default"
                and e.experiment_id != "0"
                and e.lifecycle_stage == "active"
            ]

            if experiments_to_delete:
                print(f"Found {len(experiments_to_delete)} experiment(s) to delete:")
                for exp in experiments_to_delete:
                    runs = client.search_runs(experiment_ids=[exp.experiment_id])
                    print(
                        f"  - {exp.name} (ID: {exp.experiment_id}, Runs: {len(runs)})"
                    )

                if force or confirm_deletion(
                    "Delete all these experiments and their runs?"
                ):
                    for exp in experiments_to_delete:
                        print(f"\nDeleting experiment: {exp.name}")

                        # Delete all runs
                        runs = client.search_runs(experiment_ids=[exp.experiment_id])
                        for run in runs:
                            print(f"  Deleting run {run.info.run_id[:8]}...")
                            client.delete_run(run.info.run_id)
                            time.sleep(0.05)

                        # Delete the experiment
                        print("  Deleting experiment...")
                        client.delete_experiment(exp.experiment_id)
                        print(f"  Experiment {exp.name} deleted successfully")

                    print(f"\nDeleted {len(experiments_to_delete)} experiment(s)")
                else:
                    print("Experiment deletion cancelled")
            else:
                print("No experiments to delete (keeping Default)")

        # Step 3: Clean up MinIO/S3 artifacts
        if delete_artifacts:
            cleanup_minio_artifacts(force=force)

        # Step 4: Optionally clean deleted experiments from database
        # After marking experiments as deleted, permanently remove them from DB
        if delete_experiments:
            print("\n" + "=" * 80)
            print("PERMANENT DATABASE CLEANUP (Optional)")
            print("=" * 80)
            print("Experiments have been marked as deleted in MLflow.")
            if force or confirm_deletion(
                "Also permanently remove them from the database?"
            ):
                cleanup_database_directly(force=True)

        # Summary
        print("\n" + "=" * 80)
        print("CLEANUP SUMMARY")
        print("=" * 80)

        remaining_models = client.search_registered_models()
        remaining_experiments = [
            e for e in client.search_experiments() if e.lifecycle_stage == "active"
        ]

        print(f"Remaining models: {len(remaining_models)}")
        for model in remaining_models:
            versions = client.search_model_versions(f"name='{model.name}'")
            print(f"  - {model.name} ({len(versions)} versions)")

        print(f"\nRemaining experiments: {len(remaining_experiments)}")
        for exp in remaining_experiments:
            runs = client.search_runs(experiment_ids=[exp.experiment_id])
            print(f"  - {exp.name} ({len(runs)} runs)")

    except Exception as e:
        print(f"Error during cleanup: {e}")
        return 1

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Complete cleanup of MLflow models, experiments, and artifacts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Delete only models
  python cleanup_all.py --models

  # Delete models and experiments
  python cleanup_all.py --models --experiments

  # Complete cleanup including MinIO
  python cleanup_all.py --all --artifacts

  # Keep specific models
  python cleanup_all.py --models --keep-models fraud_detector

  # Force deletion without confirmation
  python cleanup_all.py --all --artifacts --force

  # Permanently delete experiments from database
  python cleanup_all.py --reset-db

  # Complete cleanup with permanent database deletion
  python cleanup_all.py --all --artifacts --force
        """,
    )

    parser.add_argument(
        "--models", action="store_true", help="Delete all registered models"
    )
    parser.add_argument(
        "--experiments",
        action="store_true",
        help="Delete all experiments (except Default)",
    )
    parser.add_argument(
        "--artifacts", action="store_true", help="Delete all artifacts from MinIO/S3"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Delete models and experiments (use with --artifacts for complete cleanup)",
    )
    parser.add_argument("--keep-models", nargs="+", help="List of model names to keep")
    parser.add_argument(
        "--keep-experiments", nargs="+", help="List of experiment names to keep"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompts (use with caution!)",
    )
    parser.add_argument(
        "--mlflow-uri", help="MLflow tracking URI (default: http://localhost:5000)"
    )
    parser.add_argument(
        "--reset-db", action="store_true", help="Show database reset instructions"
    )

    args = parser.parse_args()

    if args.mlflow_uri:
        os.environ["MLFLOW_TRACKING_URI"] = args.mlflow_uri

    if args.reset_db:
        cleanup_database_directly(force=args.force)
        return 0

    if not (args.models or args.experiments or args.all or args.artifacts):
        print("Error: Specify cleanup options")
        parser.print_help()
        return 1

    delete_models = args.models or args.all
    delete_experiments = args.experiments or args.all

    return cleanup_mlflow(
        delete_models=delete_models,
        delete_experiments=delete_experiments,
        delete_artifacts=args.artifacts,
        keep_experiments=args.keep_experiments,
        keep_models=args.keep_models,
        force=args.force,
    )


if __name__ == "__main__":
    sys.exit(main())
