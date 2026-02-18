#!/bin/bash
# =============================================================================
# RT ML Platform - EC2 Bootstrap Script (User Data)
# =============================================================================
# This script runs automatically when the EC2 instance launches.
# It installs K3s, Docker, and deploys the ML platform.
# =============================================================================

set -e

# Configuration from Terraform template variables
ENABLE_SWAP="${enable_swap}"
SWAP_SIZE_GB="${swap_size_gb}"
ENABLE_MONITORING="${enable_monitoring}"
NODEPORT_API="${nodeport_api}"
NODEPORT_MLFLOW="${nodeport_mlflow}"
NODEPORT_GRAFANA="${nodeport_grafana}"
NODEPORT_PROMETHEUS="${nodeport_prometheus}"

# Logging
exec > >(tee /var/log/user-data.log | logger -t user-data -s 2>/dev/console) 2>&1
echo "========================================"
echo "RT ML Platform Bootstrap Starting..."
echo "Timestamp: $(date)"
echo "========================================"

# =============================================================================
# 1. System Updates and Prerequisites
# =============================================================================
echo "[1/7] Updating system packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y
apt-get install -y \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    git \
    jq \
    htop \
    unzip \
    awscli

# =============================================================================
# 2. Configure Swap (for t3.micro with limited memory)
# =============================================================================
if [ "$ENABLE_SWAP" = "true" ]; then
    echo "[2/7] Configuring swap ($${SWAP_SIZE_GB}GB)..."
    SWAP_FILE="/swapfile"
    if [ ! -f "$SWAP_FILE" ]; then
        fallocate -l $${SWAP_SIZE_GB}G $SWAP_FILE
        chmod 600 $SWAP_FILE
        mkswap $SWAP_FILE
        swapon $SWAP_FILE
        echo "$SWAP_FILE none swap sw 0 0" >> /etc/fstab
        # Optimize swap settings for low-memory instances
        echo "vm.swappiness=10" >> /etc/sysctl.conf
        echo "vm.vfs_cache_pressure=50" >> /etc/sysctl.conf
        sysctl -p
        echo "Swap configured: $(free -h | grep Swap)"
    else
        echo "Swap already exists."
    fi
else
    echo "[2/7] Swap disabled by configuration."
fi

# =============================================================================
# 3. Install Docker
# =============================================================================
echo "[3/7] Installing Docker..."
if ! command -v docker &> /dev/null; then
    # Add Docker's official GPG key
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    # Add the repository
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null

    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    # Add ubuntu user to docker group
    usermod -aG docker ubuntu

    # Start Docker
    systemctl enable docker
    systemctl start docker
    echo "Docker installed: $(docker --version)"
else
    echo "Docker already installed."
fi

# =============================================================================
# 4. Install K3s (Lightweight Kubernetes)
# =============================================================================
echo "[4/7] Installing K3s..."
if ! command -v k3s &> /dev/null; then
    # Install K3s without Traefik (we'll use NodePorts directly)
    curl -sfL https://get.k3s.io | sh -s - \
        --disable traefik \
        --write-kubeconfig-mode 644

    # Wait for K3s to be ready
    echo "Waiting for K3s to be ready..."
    sleep 30
    until k3s kubectl get nodes 2>/dev/null | grep -q "Ready"; do
        echo "Waiting for K3s node to be ready..."
        sleep 10
    done

    # Setup kubeconfig for ubuntu user
    mkdir -p /home/ubuntu/.kube
    cp /etc/rancher/k3s/k3s.yaml /home/ubuntu/.kube/config
    chown -R ubuntu:ubuntu /home/ubuntu/.kube
    chmod 600 /home/ubuntu/.kube/config

    # Add aliases to ubuntu's bashrc
    cat >> /home/ubuntu/.bashrc << 'EOF'

# K3s aliases
export KUBECONFIG=/home/ubuntu/.kube/config
alias k='sudo k3s kubectl'
alias kubectl='sudo k3s kubectl'
alias kgp='sudo k3s kubectl get pods -n ml-pipeline'
alias klogs='sudo k3s kubectl logs -n ml-pipeline'
EOF

    echo "K3s installed: $(k3s --version)"
else
    echo "K3s already installed."
fi

# =============================================================================
# 5. Pull Docker Images from GHCR
# =============================================================================
echo "[5/7] Pulling images from GHCR..."

# 5.1 Retrieve GitHub PAT from Secrets Manager
echo "Retrieving GitHub PAT..."
SECRET_ID="rt-ml-platform/gh-pat-read"
# Use IMDSv2 to get the region
TOKEN=$(curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
REGION=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" -s http://169.254.169.254/latest/meta-data/placement/region)
GH_PAT=$(aws secretsmanager get-secret-value --secret-id $SECRET_ID --region $REGION --query SecretString --output text)

if [ -z "$GH_PAT" ]; then
    echo "ERROR: Failed to retrieve GitHub PAT from Secrets Manager."
    exit 1
fi

# 5.2 Clone Repository (for K8s manifests)
echo "Cloning repository..."
cd /home/ubuntu
if [ ! -d "rt-ml-multicloud-platform" ]; then
    # Use PAT for authentication
    git clone https://ItaloPinheiro:$GH_PAT@github.com/ItaloPinheiro/rt-ml-multicloud-platform.git
    chown -R ubuntu:ubuntu rt-ml-multicloud-platform
fi

# 5.3 Login to GHCR
echo $GH_PAT | docker login ghcr.io -u ItaloPinheiro --password-stdin

# 5.4 Pull Images
# Using 'latest' tag for now, but in prod we should use specific versions passing via terraform var
IMAGE_REPO="ghcr.io/italopinheiro/rt-ml-multicloud-platform"

echo "Pulling API image..."
if ! docker pull --platform linux/amd64 $IMAGE_REPO/api:latest; then
    echo "WARNING: Failed to pull api:latest, trying api:main..."
    docker pull --platform linux/amd64 $IMAGE_REPO/api:main
    docker tag $IMAGE_REPO/api:main $IMAGE_REPO/api:latest
fi
docker tag $IMAGE_REPO/api:latest ml-pipeline/api:v1.0.0

echo "Pulling MLflow image..."
if ! docker pull --platform linux/amd64 $IMAGE_REPO/mlflow:latest; then
    echo "WARNING: Failed to pull mlflow:latest, trying mlflow:main..."
    docker pull --platform linux/amd64 $IMAGE_REPO/mlflow:main
    docker tag $IMAGE_REPO/mlflow:main $IMAGE_REPO/mlflow:latest
fi
docker tag $IMAGE_REPO/mlflow:latest ml-pipeline/mlflow:v1.0.0

# Import into K3s (since we are using local images in manifests)
# Note: In a real production setup, K3s would pull directly from GHCR using imagePullSecrets.
# For this demo, we re-tag and import to keep the manifests simple and identical to local dev.
echo "Importing images into K3s..."
docker save ml-pipeline/api:v1.0.0 | k3s ctr images import -
docker save ml-pipeline/mlflow:v1.0.0 | k3s ctr images import -

echo "Images pulled and imported successfully."

# =============================================================================
# 6. Configure Secrets & Overlay
# =============================================================================
echo "[6/7] Configuring secrets and application..."

# 6.1 Create Namespace
echo "Creating namespace..."
k3s kubectl create namespace ml-pipeline --dry-run=client -o yaml | k3s kubectl apply -f -

# 6.2 Retrieve App Secrets from Secrets Manager
echo "Retrieving App Secrets..."
APP_SECRET_ID="rt-ml-platform/app-secrets"
APP_SECRETS=$(aws secretsmanager get-secret-value --secret-id $APP_SECRET_ID --region $REGION --query SecretString --output text)

if [ -z "$APP_SECRETS" ]; then
    echo "ERROR: Failed to retrieve App Secrets from Secrets Manager."
    # Fallback to demo defaults if secret missing (for safety in demo)
    echo "WARNING: Using fallback demo secrets!"
    APP_SECRETS='{"DATABASE_USER":"mlflow","DATABASE_PASSWORD":"mlflow123secret","DATABASE_NAME":"mlflow","DATABASE_HOST":"postgres-service","REDIS_HOST":"redis-service","REDIS_PORT":"6379","REDIS_PASSWORD":"redis123secret","MLFLOW_TRACKING_URI":"http://mlflow-service:5000"}'
fi

# 6.3 Create K8s Secret directly (No file on disk)
echo "Creating K8s Secret..."
k3s kubectl create secret generic ml-pipeline-secrets -n ml-pipeline \
  --from-literal=DATABASE_USER="$(echo $APP_SECRETS | jq -r '.DATABASE_USER')" \
  --from-literal=DATABASE_PASSWORD="$(echo $APP_SECRETS | jq -r '.DATABASE_PASSWORD')" \
  --from-literal=DATABASE_NAME="$(echo $APP_SECRETS | jq -r '.DATABASE_NAME')" \
  --from-literal=DATABASE_HOST="$(echo $APP_SECRETS | jq -r '.DATABASE_HOST')" \
  --from-literal=REDIS_HOST="$(echo $APP_SECRETS | jq -r '.REDIS_HOST')" \
  --from-literal=REDIS_PORT="$(echo $APP_SECRETS | jq -r '.REDIS_PORT')" \
  --from-literal=REDIS_PASSWORD="$(echo $APP_SECRETS | jq -r '.REDIS_PASSWORD')" \
  --from-literal=MLFLOW_TRACKING_URI="$(echo $APP_SECRETS | jq -r '.MLFLOW_TRACKING_URI')" \
  --dry-run=client -o yaml | k3s kubectl apply -f -

# =============================================================================
# 7. Deploy to K3s
# =============================================================================
echo "[7/7] Deploying to Kubernetes..."

# Apply the AWS Demo overlay (which expects the secret to exist)
# Using aws-demo overlay which does NOT generate secrets (separation of concerns)
cd /home/ubuntu/rt-ml-multicloud-platform
k3s kubectl apply -k ops/k8s/overlays/aws-demo

# Wait for pods to be ready (with timeout)
echo "Waiting for pods to start (this may take several minutes)..."
sleep 90

# Check pod status
echo "Current pod status:"
k3s kubectl get pods -n ml-pipeline

# =============================================================================
# Bootstrap Complete
# =============================================================================
echo ""
echo "========================================"
echo "RT ML Platform Bootstrap Complete!"
echo "Timestamp: $(date)"
echo "========================================"
echo ""
echo "Check pod status with: sudo k3s kubectl get pods -n ml-pipeline"
echo ""
