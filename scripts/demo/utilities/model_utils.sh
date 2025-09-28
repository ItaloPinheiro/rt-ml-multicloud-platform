#!/bin/bash
# Model management utilities for MLflow

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Function to show usage
show_usage() {
    echo "Model Management Utilities for MLflow"
    echo "======================================"
    echo ""
    echo "Usage: $0 [COMMAND] [OPTIONS]"
    echo ""
    echo "Commands:"
    echo "  list                List all models and experiments"
    echo "  clean-models        Delete all registered models (with confirmation)"
    echo "  clean-experiments   Delete all experiments except Default (with confirmation)"
    echo "  clean-all          Delete all models and experiments (with confirmation)"
    echo "  clean-artifacts    Clean MinIO/S3 artifacts"
    echo "  reset              Full reset - delete everything and clean artifacts"
    echo ""
    echo "Options:"
    echo "  --force            Skip confirmation prompts"
    echo "  --keep-models      Models to keep (e.g., --keep-models fraud_detector)"
    echo "  --keep-experiments Experiments to keep (e.g., --keep-experiments production)"
    echo ""
    echo "Examples:"
    echo "  $0 list"
    echo "  $0 clean-models"
    echo "  $0 clean-all --force"
    echo "  $0 clean-models --keep-models fraud_detector"
    echo ""
}

# Function to list models
list_models() {
    print_info "Listing all models and experiments..."
    python "$SCRIPT_DIR/list_models.py"
}

# Function to clean models
clean_models() {
    local force_flag=""
    local keep_models=""

    # Parse additional arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --force)
                force_flag="--force"
                shift
                ;;
            --keep-models)
                shift
                keep_models="--keep-models"
                while [[ $# -gt 0 ]] && [[ ! "$1" =~ ^-- ]]; do
                    keep_models="$keep_models $1"
                    shift
                done
                ;;
            *)
                shift
                ;;
        esac
    done

    print_warning "Cleaning registered models..."
    python "$SCRIPT_DIR/cleanup_models.py" --models $force_flag $keep_models
}

# Function to clean experiments
clean_experiments() {
    local force_flag=""
    local keep_experiments=""

    # Parse additional arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --force)
                force_flag="--force"
                shift
                ;;
            --keep-experiments)
                shift
                keep_experiments="--keep-experiments"
                while [[ $# -gt 0 ]] && [[ ! "$1" =~ ^-- ]]; do
                    keep_experiments="$keep_experiments $1"
                    shift
                done
                ;;
            *)
                shift
                ;;
        esac
    done

    print_warning "Cleaning experiments..."
    python "$SCRIPT_DIR/cleanup_models.py" --experiments $force_flag $keep_experiments
}

# Function to clean everything
clean_all() {
    local force_flag=""

    # Parse additional arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --force)
                force_flag="--force"
                shift
                ;;
            *)
                shift
                ;;
        esac
    done

    print_warning "Cleaning all models and experiments..."
    python "$SCRIPT_DIR/cleanup_models.py" --all $force_flag
}

# Function to clean MinIO artifacts
clean_artifacts() {
    print_warning "Cleaning MinIO/S3 artifacts..."

    if [[ "$1" != "--force" ]]; then
        echo "This will delete all artifacts in MinIO."
        read -p "Are you sure? Type 'YES' to confirm: " confirm
        if [[ "$confirm" != "YES" ]]; then
            print_info "Cancelled"
            return
        fi
    fi

    # Check if MinIO container is running
    if docker ps --format '{{.Names}}' | grep -q ml-mlflow-minio; then
        print_info "Removing artifacts from MinIO..."
        docker exec ml-mlflow-minio mc rm -r --force local/mlflow/ 2>/dev/null || true
        docker exec ml-mlflow-minio mc mb local/mlflow 2>/dev/null || true
        print_success "MinIO artifacts cleaned"
    else:
        print_error "MinIO container not running"
    fi
}

# Function to reset everything
reset_all() {
    print_warning "FULL RESET - This will delete all models, experiments, and artifacts!"

    if [[ "$1" != "--force" ]]; then
        echo "This action cannot be undone."
        read -p "Are you sure? Type 'RESET' to confirm: " confirm
        if [[ "$confirm" != "RESET" ]]; then
            print_info "Cancelled"
            return
        fi
    fi

    # Clean models and experiments
    python "$SCRIPT_DIR/cleanup_models.py" --all --force

    # Clean artifacts
    clean_artifacts --force

    print_success "Full reset complete"
}

# Main script logic
main() {
    case "${1:-}" in
        list)
            list_models
            ;;
        clean-models)
            shift
            clean_models "$@"
            ;;
        clean-experiments)
            shift
            clean_experiments "$@"
            ;;
        clean-all)
            shift
            clean_all "$@"
            ;;
        clean-artifacts)
            shift
            clean_artifacts "$@"
            ;;
        reset)
            shift
            reset_all "$@"
            ;;
        -h|--help|help|"")
            show_usage
            ;;
        *)
            print_error "Unknown command: $1"
            echo ""
            show_usage
            exit 1
            ;;
    esac
}

# Run main function
main "$@"