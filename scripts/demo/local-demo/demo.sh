#!/bin/bash
# =============================================================================
# Comprehensive ML Pipeline Demo Script with Model Versioning
# =============================================================================

set -e  # Exit on any error

# Configuration
DATA_ROOT=${DATA_ROOT:-data/sample}
DEMO_DATA="${DATA_ROOT}/demo"

# Source demo configuration if available
if [ -f "${DEMO_DATA}/demo.env" ]; then
    source "${DEMO_DATA}/demo.env"
else
    # Fallback configuration
    DEMO_DATASET="${DEMO_DATA}/datasets/fraud_detection.csv"
    DEMO_REQUEST_V1="${DEMO_DATA}/requests/baseline.json"
    DEMO_REQUEST_V2="${DEMO_DATA}/requests/improved.json"
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
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

print_highlight() {
    echo -e "${CYAN}[DEMO]${NC} $1"
}

print_section() {
    echo ""
    echo -e "${MAGENTA}════════════════════════════════════════════════════════════════${NC}"
    echo -e "${MAGENTA}  $1${NC}"
    echo -e "${MAGENTA}════════════════════════════════════════════════════════════════${NC}"
    echo ""
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

# Function to show countdown
countdown() {
    local seconds=$1
    local message=$2

    echo ""
    for ((i=seconds; i>0; i--)); do
        printf "\r${YELLOW}[WAIT]${NC} $message: ${YELLOW}$i${NC} seconds remaining..."
        sleep 1
    done
    printf "\r${GREEN}[DONE]${NC} $message completed!                     \n"
}

main() {
    clear
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║     🚀 COMPREHENSIVE ML PIPELINE DEMO WITH MODEL VERSIONING     ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════════════╝${NC}"

    # =========================================================================
    print_section "INITIAL CLEANUP: REMOVING EXISTING CONTAINERS"
    # =========================================================================

    print_status "Checking for existing containers..."

    # Stop and remove any existing ML containers
    existing_containers=$(docker ps -aq --filter "name=ml-" 2>/dev/null | wc -l)

    if [ "$existing_containers" -gt 0 ]; then
        print_status "Found existing ML containers. Cleaning up..."

        # Stop all ML containers
        docker ps -q --filter "name=ml-" | xargs -r docker stop 2>/dev/null || true

        # Remove all ML containers
        docker ps -aq --filter "name=ml-" | xargs -r docker rm -f 2>/dev/null || true

        print_success "Removed $existing_containers existing containers"
    else
        print_status "No existing ML containers found"
    fi

    # Remove project-specific volumes (this will wipe all data including database)
    print_status "Removing project volumes (will wipe all data)..."
    docker volume ls --format "{{.Name}}" | grep "rt-ml-multicloud-platform" | while read vol; do
        docker volume rm "$vol" 2>/dev/null || true
        echo "  Removed volume: $vol"
    done

    # Also remove any unnamed/orphaned volumes
    docker volume prune -f 2>/dev/null || true

    # Remove the network if it exists
    if docker network ls | grep -q "ml-pipeline-network"; then
        print_status "Removing existing network..."
        docker network rm ml-pipeline-network 2>/dev/null || true
    fi

    print_success "Initial cleanup completed"
    sleep 2

    # =========================================================================
    print_section "STEP 1: STARTING SERVICES"
    # =========================================================================

    print_status "Starting all services with Docker Compose..."
    docker-compose -f ops/local/docker-compose.yml -f ops/local/docker-compose.override.yml up -d
    print_success "Services started"

    # Give services time to initialize
    print_status "Waiting for services to initialize..."
    sleep 10

    # Wait for core services
    wait_for_service "http://localhost:5000/health" "MLflow"
    wait_for_service "http://localhost:8000/health" "Model API"
    wait_for_service "http://localhost:9001/login" "MinIO Console"

    # =========================================================================
    print_section "STEP 2: TRAINING FIRST MODEL (Version 1)"
    # =========================================================================

    print_highlight "Training initial fraud detection model..."

    # Start beam-runner container
    print_status "Starting beam-runner container..."
    docker-compose -f ops/local/docker-compose.yml -f ops/local/docker-compose.override.yml --profile beam up -d beam-runner
    sleep 5

    # Train first model
    if [ -f "src/models/training/train.py" ]; then
        print_status "Training model version 1..."
        # Use docker exec with sh -c to avoid path issues on Windows
        docker exec ml-beam-runner sh -c "python -m src.models.training.train \
            --data-path /app/${DEMO_DATASET} \
            --mlflow-uri http://mlflow-server:5000 \
            --experiment fraud_detection \
            --model-name fraud_detector"
        print_success "Model version 1 trained and registered!"
    else
        print_error "Training script not found"
        exit 1
    fi

    # =========================================================================
    print_section "STEP 3: CHECKING MODEL IN MLFLOW"
    # =========================================================================

    print_highlight "Checking registered model in MLflow..."
    echo ""

    # List models using MLflow API
    print_status "Fetching model details from MLflow..."
    response=$(curl -s http://localhost:5000/api/2.0/mlflow/registered-models/search \
        -H "Content-Type: application/json" \
        -d '{"filter": "name=\"fraud_detector\""}')

    if [ $? -eq 0 ]; then
        echo "$response" | python -m json.tool 2>/dev/null | head -20 || echo "$response"
        print_success "Model found in MLflow registry!"
    fi

    # Open MLflow UI
    print_highlight "📊 MLflow UI available at: http://localhost:5000"
    print_status "Navigate to Models tab to see 'fraud_detector' model"

    # =========================================================================
    print_section "STEP 4: VERIFYING MODEL STORAGE IN MINIO S3"
    # =========================================================================

    print_highlight "Checking model artifacts in MinIO S3..."
    echo ""

    # List objects in MinIO
    print_status "Listing artifacts in MinIO bucket 'mlflow'..."
    docker exec ml-mlflow-minio mc ls local/mlflow/ --recursive | head -10

    print_highlight "📦 MinIO Console available at: http://localhost:9001"
    print_status "Login: minioadmin / minioadmin123"

    # =========================================================================
    print_section "STEP 5: CHECKING CURRENT MODEL IN API"
    # =========================================================================

    print_highlight "Checking which model is currently loaded in the API..."
    echo ""

    # Get current model info
    print_status "Fetching current model information from API..."
    model_info=$(curl -s http://localhost:8000/models)

    if [ $? -eq 0 ] && [ -n "$model_info" ]; then
        echo "$model_info" | python -m json.tool 2>/dev/null | grep -A 10 '"fraud_detector"' | head -15
    else
        print_error "Failed to fetch model information"
    fi

    # =========================================================================
    print_section "STEP 6: MAKING PREDICTION WITH VERSION 1"
    # =========================================================================

    print_highlight "Testing prediction with model version 1..."
    echo ""

    # Make a prediction
    print_status "Sending prediction request using sample_request_1.json..."
    prediction=$(curl -s -X POST http://localhost:8000/predict \
        -H "Content-Type: application/json" \
        -d @${DEMO_REQUEST_V1})

    if [ $? -eq 0 ] && [ -n "$prediction" ]; then
        echo "$prediction" | python -m json.tool 2>/dev/null || echo "$prediction"
        print_success "Prediction successful with version 1!"
    fi

    # =========================================================================
    print_section "STEP 7: TRAINING NEW MODEL VERSION (Version 2)"
    # =========================================================================

    print_highlight "Training an improved model (version 2)..."
    echo ""

    # Train second model with different parameters
    print_status "Training model version 2 with updated parameters..."
    docker exec ml-beam-runner sh -c "python -m src.models.training.train \
        --data-path /app/${DEMO_DATASET} \
        --mlflow-uri http://mlflow-server:5000 \
        --experiment fraud_detection \
        --model-name fraud_detector \
        --n-estimators 150"

    print_success "Model version 2 trained and promoted to Production!"

    # Show model versions
    print_status "Listing all model versions..."
    python scripts/model_scripts/list_models.py 2>/dev/null | grep -A 5 "fraud_detector" || true

    # =========================================================================
    print_section "STEP 8: WAITING FOR AUTO-UPDATE (60 seconds)"
    # =========================================================================

    print_highlight "Model API checks for updates every 60 seconds..."
    print_status "The API will automatically detect and load the new Production model"

    # Show countdown
    countdown 65 "Waiting for automatic model update"

    # =========================================================================
    print_section "STEP 9: VERIFYING NEW MODEL IN API"
    # =========================================================================

    print_highlight "Checking if API has loaded the new model version..."
    echo ""

    # Get updated model info
    print_status "Fetching updated model information from API..."
    new_model_info=$(curl -s http://localhost:8000/models)

    if [ $? -eq 0 ] && [ -n "$new_model_info" ]; then
        # Show only fraud_detector models
        echo "$new_model_info" | python -m json.tool 2>/dev/null | grep -A 10 '"fraud_detector"' | head -15
        print_success "API models list updated!"
    fi

    # =========================================================================
    print_section "STEP 10: MAKING PREDICTION WITH VERSION 2"
    # =========================================================================

    print_highlight "Testing prediction with the new model version..."
    echo ""

    # Make prediction with new model
    print_status "Sending prediction request to new model using sample_request_2.json..."
    new_prediction=$(curl -s -X POST http://localhost:8000/predict \
        -H "Content-Type: application/json" \
        -d @${DEMO_REQUEST_V2})

    if [ $? -eq 0 ] && [ -n "$new_prediction" ]; then
        echo "$new_prediction" | python -m json.tool 2>/dev/null || echo "$new_prediction"
        print_success "Prediction successful with version 2!"
    fi

    # =========================================================================
    print_section "DEMO COMPLETE! 🎉"
    # =========================================================================
}

# Run main function
main "$@"