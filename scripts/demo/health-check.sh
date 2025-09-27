#!/bin/bash
# =============================================================================
# Health Check Script for ML Pipeline Platform
# =============================================================================

set -e

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

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Function to check service health
check_service() {
    local url=$1
    local service_name=$2
    local expected_status=${3:-200}

    print_status "Checking $service_name..."

    if response=$(curl -s -w "%{http_code}" -o /dev/null "$url" 2>/dev/null); then
        if [ "$response" -eq "$expected_status" ]; then
            print_success "$service_name is healthy (HTTP $response)"
            return 0
        else
            print_error "$service_name returned HTTP $response (expected $expected_status)"
            return 1
        fi
    else
        print_error "$service_name is not responding"
        return 1
    fi
}

# Function to check Docker container status
check_container() {
    local container_name=$1
    local status=$(docker-compose ps -q "$container_name" 2>/dev/null | xargs docker inspect --format '{{.State.Status}}' 2>/dev/null)

    if [ "$status" = "running" ]; then
        print_success "$container_name container is running"
        return 0
    elif [ "$status" = "exited" ]; then
        print_error "$container_name container has exited"
        return 1
    elif [ -z "$status" ]; then
        print_error "$container_name container not found"
        return 1
    else
        print_warning "$container_name container status: $status"
        return 1
    fi
}

main() {
    echo "🏥 ML Pipeline Platform Health Check"
    echo "===================================="

    local all_healthy=true

    # Check Docker containers
    print_status "Checking Docker containers..."

    containers=("postgres" "redis" "mlflow-server" "model-api" "prometheus" "grafana")
    for container in "${containers[@]}"; do
        if ! check_container "$container"; then
            all_healthy=false
        fi
    done

    echo ""

    # Check service endpoints
    print_status "Checking service endpoints..."

    # Core API services
    if ! check_service "http://localhost:8000/health" "Model API"; then
        all_healthy=false
    fi

    if ! check_service "http://localhost:5000/health" "MLflow Server"; then
        all_healthy=false
    fi

    # Monitoring services
    if ! check_service "http://localhost:9090/-/healthy" "Prometheus"; then
        all_healthy=false
    fi

    if ! check_service "http://localhost:3001/api/health" "Grafana"; then
        all_healthy=false
    fi

    # Storage services
    if ! check_service "http://localhost:9001/minio/health/live" "MinIO" 200; then
        all_healthy=false
    fi

    # Message broker
    if ! check_service "http://localhost:8082/topics" "Redpanda Console"; then
        all_healthy=false
    fi

    echo ""

    # Check API functionality
    print_status "Testing API functionality..."

    # Test health endpoint with detailed response
    if response=$(curl -s "http://localhost:8000/health" 2>/dev/null); then
        if echo "$response" | grep -q "healthy"; then
            print_success "API health endpoint working"
        else
            print_warning "API responding but health status unclear"
            echo "Response: $response"
        fi
    else
        print_error "Cannot reach API health endpoint"
        all_healthy=false
    fi

    # Test metrics endpoint
    if curl -s "http://localhost:8000/metrics" >/dev/null 2>&1; then
        print_success "Metrics endpoint accessible"
    else
        print_warning "Metrics endpoint not accessible"
    fi

    echo ""

    # Final status
    if [ "$all_healthy" = true ]; then
        print_success "All services are healthy! 🎉"
        echo ""
        echo "Access points:"
        echo "  - Model API: http://localhost:8000"
        echo "  - API Documentation: http://localhost:8000/docs"
        echo "  - MLflow UI: http://localhost:5000"
        echo "  - Prometheus: http://localhost:9090"
        echo "  - Grafana: http://localhost:3001 (admin/admin123)"
        echo "  - MinIO Console: http://localhost:9001 (minioadmin/minioadmin123)"
        echo "  - Redpanda Console: http://localhost:8082"
        echo ""
        exit 0
    else
        print_error "Some services are not healthy. Check the logs for more details."
        echo ""
        echo "Troubleshooting commands:"
        echo "  # View service logs"
        echo "  docker-compose logs <service-name>"
        echo ""
        echo "  # Restart all services"
        echo "  docker-compose restart"
        echo ""
        echo "  # Restart specific service"
        echo "  docker-compose restart <service-name>"
        echo ""
        exit 1
    fi
}

# Run main function
main "$@"