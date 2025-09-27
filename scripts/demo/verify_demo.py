#!/usr/bin/env python3
"""
Verify demo setup and files without requiring external dependencies.
"""

import os
import json
import sys
from pathlib import Path

def check_file(filepath, description="file"):
    """Check if file exists and return status."""
    if os.path.exists(filepath):
        print(f"[OK] {description}: {filepath}")
        return True
    else:
        print(f"[MISSING] {description}: {filepath}")
        return False

def check_directory(dirpath, description="directory"):
    """Check if directory exists and return status."""
    if os.path.exists(dirpath) and os.path.isdir(dirpath):
        print(f"[OK] {description}: {dirpath}")
        return True
    else:
        print(f"[MISSING] {description}: {dirpath}")
        return False

def verify_sample_data():
    """Verify sample data files."""
    print("\nChecking sample data files...")

    sample_dir = "sample_data/small"
    files_to_check = [
        ("sample_transactions.json", "transaction data"),
        ("sample_user_features.json", "user features"),
    ]

    all_present = check_directory(sample_dir, "sample data directory")

    for filename, description in files_to_check:
        filepath = os.path.join(sample_dir, filename)
        all_present &= check_file(filepath, description)

        # Try to validate JSON structure
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, list) and len(data) > 0:
                        print(f"   [INFO] {description} contains {len(data)} records")
                    else:
                        print(f"   [WARNING] {description} appears to be empty or invalid")
            except json.JSONDecodeError as e:
                print(f"   [ERROR] {description} contains invalid JSON: {e}")
                all_present = False

    return all_present

def verify_scripts():
    """Verify demo scripts."""
    print("\nChecking demo scripts...")

    scripts_to_check = [
        ("scripts/demo/demo.sh", "main demo script"),
        ("scripts/demo/generate_data.py", "data generation script"),
        ("scripts/demo/train_model.py", "model training script"),
        ("scripts/demo/health-check.sh", "health check script"),
        ("scripts/demo/load_sample_data.py", "sample data loader"),
        ("scripts/demo/verify_demo.py", "demo verification script"),
        ("scripts/setup.sh", "setup script"),
    ]

    all_present = True
    for filepath, description in scripts_to_check:
        all_present &= check_file(filepath, description)

    return all_present

def verify_configuration():
    """Verify configuration files."""
    print("\nChecking configuration files...")

    config_files = [
        ("docker-compose.yml", "Docker Compose configuration"),
        (".env.example", "environment template"),
        ("monitoring/prometheus/prometheus.yml", "Prometheus configuration"),
        ("monitoring/grafana/datasources/prometheus.yml", "Grafana datasource"),
        ("monitoring/grafana/dashboards/dashboard.yml", "Grafana dashboard config"),
    ]

    all_present = True
    for filepath, description in config_files:
        all_present &= check_file(filepath, description)

    return all_present

def verify_dockerfiles():
    """Verify Docker build files."""
    print("\nChecking Docker build files...")

    docker_files = [
        ("docker/Dockerfile", "main Dockerfile"),
        ("docker/api.Dockerfile", "API Dockerfile"),
        ("docker/mlflow.Dockerfile", "MLflow Dockerfile"),
        ("docker/beam.Dockerfile", "Beam Dockerfile"),
    ]

    all_present = True
    for filepath, description in docker_files:
        all_present &= check_file(filepath, description)

    return all_present

def verify_source_structure():
    """Verify source code structure."""
    print("\nChecking source code structure...")

    source_dirs = [
        ("src", "source code"),
        ("src/api", "API source"),
        ("src/models", "models source"),
        ("src/feature_store", "feature store source"),
        ("src/ingestion", "ingestion source"),
        ("configs", "configuration directory"),
    ]

    all_present = True
    for dirpath, description in source_dirs:
        all_present &= check_directory(dirpath, description)

    return all_present

def main():
    """Main verification function."""
    print("Verifying ML Pipeline Demo Setup")
    print("=" * 40)

    # Check current directory
    cwd = Path.cwd()
    print(f"Working directory: {cwd}")

    # Run all verification checks
    checks = [
        ("Sample Data", verify_sample_data),
        ("Demo Scripts", verify_scripts),
        ("Configuration", verify_configuration),
        ("Docker Files", verify_dockerfiles),
        ("Source Structure", verify_source_structure),
    ]

    all_passed = True
    results = {}

    for check_name, check_func in checks:
        print(f"\n" + "=" * 40)
        try:
            result = check_func()
            results[check_name] = result
            all_passed &= result
        except Exception as e:
            print(f"[ERROR] Error during {check_name} check: {e}")
            results[check_name] = False
            all_passed = False

    # Summary
    print(f"\n" + "=" * 40)
    print("VERIFICATION SUMMARY")
    print("=" * 40)

    for check_name, result in results.items():
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status} {check_name}")

    if all_passed:
        print(f"\nAll checks passed! Demo setup is ready.")
        print(f"\nNext steps:")
        print(f"  1. Install dependencies: poetry install")
        print(f"  2. Start services: docker-compose up -d")
        print(f"  3. Run demo: ./scripts/demo/demo.sh")
        return True
    else:
        print(f"\nSome checks failed. Please review the issues above.")
        print(f"\nTo fix missing files:")
        print(f"  1. Run data generation: python scripts/demo/generate_data.py")
        print(f"  2. Check file paths and permissions")
        print(f"  3. Ensure all dependencies are installed")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)