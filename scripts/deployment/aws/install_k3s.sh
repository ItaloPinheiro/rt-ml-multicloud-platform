#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting Zero-Cost EC2 Deployment...${NC}"

# 1. Install Docker
echo -e "${GREEN}[1/5] Installing Docker...${NC}"
if ! command -v docker &> /dev/null; then
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl gnupg
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    echo \
      "deb [arch=\"$(dpkg --print-architecture)\" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    sudo usermod -aG docker $USER
    echo "Docker installed. Please log out and back in if you get permission errors, or run this script with sudo."
else
    echo "Docker already installed."
fi

# 2. Install K3s
echo -e "${GREEN}[2/5] Installing K3s...${NC}"
if ! command -v kubectl &> /dev/null; then
    curl -sfL https://get.k3s.io | sh -
    # Setup kubeconfig for current user
    mkdir -p ~/.kube
    sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
    sudo chown $USER:$USER ~/.kube/config
    echo "export KUBECONFIG=~/.kube/config" >> ~/.bashrc
    export KUBECONFIG=~/.kube/config
else
    echo "K3s/kubectl already installed."
fi

export KUBECONFIG=~/.kube/config

# 3. Build Docker Images
echo -e "${GREEN}[3/5] Building Docker Images (this may take a while)...${NC}"
# We build with the tags expected by the k8s manifests, but since we are local,
# we need to make sure k3s can see them.
# K3s uses containerd. We can import docker images to k3s.

# Build API
sudo docker build -t ml-pipeline/api:v1.0.0 -f ops/docker/api/Dockerfile .
# Build MLflow
sudo docker build -t ml-pipeline/mlflow:v1.0.0 -f ops/docker/mlflow/Dockerfile .

# Save and import to K3s (simplest way for local images in k3s without registry)
echo "Importing images to K3s..."
sudo docker save ml-pipeline/api:v1.0.0 | sudo k3s ctr images import -
sudo docker save ml-pipeline/mlflow:v1.0.0 | sudo k3s ctr images import -

# 4. Configure Manifests
# echo -e "${GREEN}[4/5] Configuring Kubernetes Manifests...${NC}"

# We will handle Kustomization manually for sequential deployment.
mkdir -p ops/k8s/overlays/local-dev
# cp k8s/overlays/production/* k8s/overlays/local-dev/ 2>/dev/null || true
# cp ops/k8s/overlays/production/kustomization.yaml ops/k8s/overlays/local-dev/

# 5. Deploy
echo -e "${GREEN}[5/5] Deploying to K3s...${NC}"
# We assume secrets.env is already there or handled by the user manually transferring it.
# But since we are automating "everything fresh", we should try to apply if the overlay is ready.
if [ -f "ops/k8s/overlays/local-dev/kustomization.yaml" ]; then
    sudo kubectl kustomize ops/k8s/overlays/local-dev --load-restrictor LoadRestrictionsNone | sudo kubectl apply -f -
else
    echo "Warning: ops/k8s/overlays/local-dev/kustomization.yaml not found. Skipping deployment."
fi

echo -e "${GREEN}Deployment Applied! Checking status...${NC}"
sudo kubectl get pods -n ml-pipeline-prod
