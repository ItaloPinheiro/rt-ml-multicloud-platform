#!/bin/bash
# =============================================================================
# ML Pipeline Platform Setup Script
# =============================================================================

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Main setup function
main() {
    echo "🚀 Setting up ML Pipeline Platform..."
    echo "======================================="

    # Check prerequisites
    print_status "Checking prerequisites..."

    if ! command_exists docker; then
        print_error "Docker is required but not installed. Please install Docker first."
        exit 1
    fi

    if ! command_exists python3; then
        print_error "Python 3.11+ is required but not installed."
        exit 1
    fi

    # Check Python version
    python_version=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    if [[ "$(printf '%s\n' "3.11" "$python_version" | sort -V | head -n1)" != "3.11" ]]; then
        print_warning "Python 3.11+ recommended, found $python_version"
    fi

    print_success "Prerequisites check passed"

    # Create necessary directories
    print_status "Creating directories..."
    mkdir -p data/{raw,features,predictions}
    mkdir -p logs
    mkdir -p models
    print_success "Directories created"

    # Install Poetry if not present
    if ! command_exists poetry; then
        print_status "Installing Poetry..."
        curl -sSL https://install.python-poetry.org | python3 -
        export PATH="$HOME/.local/bin:$PATH"
    fi
    print_success "Poetry available"

    # Install Python dependencies
    print_status "Installing Python dependencies..."
    poetry install --no-interaction --no-ansi
    print_success "Dependencies installed"

    # Create environment file if it doesn't exist
    if [ ! -f .env ]; then
        print_status "Creating environment file..."
        cp .env.example .env
        print_warning "Please update .env with your specific configuration"
    fi

    # Initialize Docker volumes and networks
    print_status "Setting up Docker environment..."
    docker network create ml-pipeline-network 2>/dev/null || true

    # Start MinIO first to create bucket
    print_status "Starting MinIO for MLflow artifacts..."
    docker-compose up -d mlflow-minio
    sleep 10

    # Create MLflow bucket
    print_status "Creating MLflow bucket..."
    docker exec ml-mlflow-minio mc config host add minio http://localhost:9000 minioadmin minioadmin123 2>/dev/null || true
    docker exec ml-mlflow-minio mc mb minio/mlflow 2>/dev/null || true
    print_success "MLflow bucket created"

    # Build Docker images
    print_status "Building Docker images..."
    docker-compose build
    print_success "Docker images built"

    echo ""
    print_success "Setup complete! 🎉"
    echo ""
    echo "Next steps:"
    echo "  1. Update .env with your cloud credentials"
    echo "  2. Run: docker-compose up -d"
    echo "  3. Run: ./scripts/demo/demo.sh"
    echo ""
    echo "Access points:"
    echo "  - MLflow UI: http://localhost:5000"
    echo "  - Model API: http://localhost:8000"
    echo "  - API Docs: http://localhost:8000/docs"
    echo "  - Prometheus: http://localhost:9090"
    echo "  - Grafana: http://localhost:3001 (admin/admin123)"
    echo "  - MinIO Console: http://localhost:9001 (minioadmin/minioadmin123)"
}

# Run main function
main "$@"