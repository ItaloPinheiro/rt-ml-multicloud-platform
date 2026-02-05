#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting Local Kubernetes Deployment Test...${NC}"

# 1. Check Prerequisites
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: Docker is not installed or not in PATH.${NC}"
    exit 1
fi

if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl is not installed. Please enable Kubernetes in Docker Desktop settings.${NC}"
    exit 1
fi

# Check connectivity
if ! kubectl cluster-info &> /dev/null; then
    echo -e "${RED}Error: Cannot connect to Kubernetes cluster. Is Docker Desktop running?${NC}"
    exit 1
fi

# 2. Build Docker Images
echo -e "${GREEN}[1/3] Building Docker Images locally...${NC}"

# API
echo "Building API Image..."
docker build -t ml-pipeline/api:v1.0.0 -f ops/docker/api/Dockerfile .

# MLflow
echo "Building MLflow Image..."
docker build -t ml-pipeline/mlflow:v1.0.0 -f ops/docker/mlflow/Dockerfile .

echo "Images built successfully. Docker Desktop shares images with local K8s automatically."

# 3. Deploy to Kubernetes
echo -e "${GREEN}[2/3] Deploying to Local Kubernetes...${NC}"

# Ensure overlay exists
if [ ! -f "ops/k8s/overlays/ec2-local/kustomization.yaml" ]; then
    echo -e "${RED}Error: Overlay ops/k8s/overlays/ec2-local/kustomization.yaml not found.${NC}"
    exit 1
fi

# Ensure namespace exists
kubectl create namespace ml-pipeline-prod --dry-run=client -o yaml | kubectl apply -f -

# Apply Manifests
# Note: We use the same ec2-local overlay because it uses NodePorts which are accessible on localhost
kubectl kustomize ops/k8s/overlays/ec2-local --load-restrictor LoadRestrictionsNone | kubectl apply -f -

# 4. Verification Instructions
echo -e "${GREEN}[3/3] Deployment complete!${NC}"
echo "Wait a few moments for pods to start."
echo "Check status: kubectl get pods -n ml-pipeline-prod"
echo "Access API:    http://localhost:30001/docs"
echo "Access MLflow: http://localhost:30000"
