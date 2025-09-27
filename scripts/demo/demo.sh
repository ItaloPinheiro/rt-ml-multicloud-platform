#!/bin/bash
# =============================================================================
# ML Pipeline Platform Demo Script
# =============================================================================

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to wait for service
wait_for_service() {
    local url=$1
    local service_name=$2
    local max_attempts=30
    local attempt=1

    print_status "Waiting for $service_name to be ready..."

    while [ $attempt -le $max_attempts ]; do
        if curl -s -f "$url" > /dev/null 2>&1; then
            print_success "$service_name is ready!"
            return 0
        fi

        echo -n "."
        sleep 2
        ((attempt++))
    done

    print_error "$service_name failed to start within expected time"
    return 1
}

main() {
    echo "🎯 Starting ML Pipeline Demo..."
    echo "==============================="

    # Start all services
    print_status "Starting all services..."
    docker-compose up -d
    print_success "Services started"

    # Wait for core services
    wait_for_service "http://localhost:5000/health" "MLflow"
    wait_for_service "http://localhost:8000/health" "Model API"
    wait_for_service "http://localhost:9090/-/healthy" "Prometheus"
    wait_for_service "http://localhost:3001/api/health" "Grafana"

    # Generate sample data
    print_status "Generating sample data..."
    if [ -f "scripts/demo/generate_data.py" ]; then
        poetry run python scripts/demo/generate_data.py
        print_success "Sample data generated"
    else
        print_error "Data generation script not found"
    fi

    # Train a demo model
    print_status "Training demo model..."
    if [ -f "scripts/demo/train_model.py" ]; then
        poetry run python scripts/demo/train_model.py
        print_success "Demo model trained"
    else
        print_error "Model training script not found"
    fi

    # Test prediction API
    print_status "Testing prediction API..."

    response=$(curl -s -X POST http://localhost:8000/predict \
        -H "Content-Type: application/json" \
        -d '{
            "features": {
                "amount": 250.00,
                "merchant_category": "electronics",
                "hour_of_day": 14,
                "is_weekend": false
            },
            "model_name": "fraud_detector"
        }' 2>/dev/null)

    if [ $? -eq 0 ] && [ -n "$response" ]; then
        print_success "API test successful!"
        echo "Response: $response"
    else
        print_error "API test failed"
    fi

    echo ""
    print_success "Demo complete! 🎉"
    echo ""
    echo "Access points:"
    echo "  - MLflow UI: http://localhost:5000"
    echo "  - Model API: http://localhost:8000"
    echo "  - API Documentation: http://localhost:8000/docs"
    echo "  - Prometheus: http://localhost:9090"
    echo "  - Grafana: http://localhost:3001 (admin/admin123)"
    echo "  - MinIO Console: http://localhost:9001 (minioadmin/minioadmin123)"
    echo ""
    echo "Try these commands:"
    echo "  # Health check all services"
    echo "  curl http://localhost:8000/health"
    echo ""
    echo "  # Make a prediction"
    echo "  curl -X POST http://localhost:8000/predict \\"
    echo "    -H 'Content-Type: application/json' \\"
    echo "    -d '{\"features\": {\"amount\": 100.0}}'"
    echo ""
    echo "  # View logs"
    echo "  docker-compose logs -f model-api"
}

# Run main function
main "$@"