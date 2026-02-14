#!/bin/bash
# =============================================================================
# RT ML Platform - EC2 Bootstrap Script (User Data)
# =============================================================================
# This script runs automatically when the EC2 instance launches.
# It installs K3s, Docker, and deploys the ML platform.
# =============================================================================

set -e

# Configuration from Terraform template variables
ENABLE_SWAP="true"
SWAP_SIZE_GB="2"
ENABLE_MONITORING="true"
NODEPORT_API="30800"
NODEPORT_MLFLOW="30500"
NODEPORT_GRAFANA="30300"
NODEPORT_PROMETHEUS="30900"

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
    echo "[2/7] Configuring swap (${SWAP_SIZE_GB}GB)..."
    SWAP_FILE="/swapfile"
    if [ ! -f "$SWAP_FILE" ]; then
        fallocate -l ${SWAP_SIZE_GB}G $SWAP_FILE
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
docker pull $IMAGE_REPO/api:latest
docker tag $IMAGE_REPO/api:latest ml-pipeline/api:v1.0.0

echo "Pulling MLflow image..."
docker pull $IMAGE_REPO/mlflow:latest
docker tag $IMAGE_REPO/mlflow:latest ml-pipeline/mlflow:v1.0.0

# Import into K3s (since we are using local images in manifests)
# Note: In a real production setup, K3s would pull directly from GHCR using imagePullSecrets.
# For this demo, we re-tag and import to keep the manifests simple and identical to local dev.
echo "Importing images into K3s..."
docker save ml-pipeline/api:v1.0.0 | k3s ctr images import -
docker save ml-pipeline/mlflow:v1.0.0 | k3s ctr images import -

echo "Images pulled and imported successfully."

# =============================================================================
# 6. Create Terraform-specific Kustomize Overlay
# =============================================================================
echo "[6/7] Configuring Kubernetes manifests..."

# Create terraform overlay directory
cd /home/ubuntu/rt-ml-multicloud-platform
OVERLAY_DIR="ops/k8s/overlays/terraform-demo"
mkdir -p $OVERLAY_DIR

# Create secrets patch file
cat > $OVERLAY_DIR/secret-patch.yaml << 'EOF'
apiVersion: v1
kind: Secret
metadata:
  name: ml-pipeline-secrets
  namespace: ml-pipeline
type: Opaque
stringData:
  DATABASE_USER: mlflow
  DATABASE_PASSWORD: mlflow123secret
  DATABASE_NAME: mlflow
  DATABASE_HOST: postgres-service
  REDIS_HOST: redis-service
  REDIS_PORT: "6379"
  REDIS_PASSWORD: redis123secret
  MLFLOW_TRACKING_URI: http://mlflow-service:5000
EOF

# Create kustomization with dynamic NodePorts
cat > $OVERLAY_DIR/kustomization.yaml << KUSTOMIZE_EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: ml-pipeline

resources:
  - ../../base

patches:
  # Patch the base secret with actual values
  - path: secret-patch.yaml
    target:
      kind: Secret
      name: ml-pipeline-secrets

  # PostgreSQL - minimal resources
  - target:
      kind: Deployment
      name: postgres
    patch: |-
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: postgres
      spec:
        template:
          spec:
            containers:
            - name: postgres
              resources:
                requests:
                  memory: "128Mi"
                  cpu: "50m"
                limits:
                  memory: "256Mi"
                  cpu: "250m"

  # Redis - minimal resources
  - target:
      kind: Deployment
      name: redis
    patch: |-
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: redis
      spec:
        template:
          spec:
            containers:
            - name: redis
              args: ["--requirepass", "\$(REDIS_PASSWORD)", "--maxmemory", "64mb", "--maxmemory-policy", "allkeys-lru"]
              resources:
                requests:
                  memory: "64Mi"
                  cpu: "25m"
                limits:
                  memory: "128Mi"
                  cpu: "100m"

  # MLflow - use local image
  - target:
      kind: Deployment
      name: mlflow
    patch: |-
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: mlflow
      spec:
        template:
          spec:
            containers:
            - name: mlflow
              image: ml-pipeline/mlflow:v1.0.0
              imagePullPolicy: Never
              args:
              - "--backend-store-uri"
              - "postgresql://\$(DATABASE_USER):\$(DATABASE_PASSWORD)@\$(DATABASE_HOST):5432/\$(DATABASE_NAME)"
              - "--artifacts-destination"
              - "/mlflow/artifacts"
              - "--serve-artifacts"
              - "--host"
              - "0.0.0.0"
              - "--port"
              - "5000"
              resources:
                requests:
                  memory: "512Mi"
                  cpu: "250m"
                limits:
                  memory: "1Gi"
                  cpu: "1000m"
              livenessProbe:
                httpGet:
                  path: /health
                  port: 5000
                initialDelaySeconds: 90
                periodSeconds: 30
                timeoutSeconds: 10
                failureThreshold: 5
              readinessProbe:
                httpGet:
                  path: /health
                  port: 5000
                initialDelaySeconds: 60
                periodSeconds: 15
                timeoutSeconds: 10
                failureThreshold: 5

  # MLflow Service - NodePort
  - target:
      kind: Service
      name: mlflow-service
    patch: |-
      apiVersion: v1
      kind: Service
      metadata:
        name: mlflow-service
      spec:
        type: NodePort
        ports:
        - port: 5000
          targetPort: 5000
          nodePort: ${NODEPORT_MLFLOW}

  # API - use local image
  - target:
      kind: Deployment
      name: ml-pipeline-api
    patch: |-
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: ml-pipeline-api
      spec:
        replicas: 1
        template:
          spec:
            containers:
            - name: api
              image: ml-pipeline/api:v1.0.0
              imagePullPolicy: Never
              resources:
                requests:
                  memory: "512Mi"
                  cpu: "250m"
                limits:
                  memory: "1Gi"
                  cpu: "1000m"
              livenessProbe:
                httpGet:
                  path: /health
                  port: 8000
                initialDelaySeconds: 90
                periodSeconds: 30
                timeoutSeconds: 10
                failureThreshold: 5
              readinessProbe:
                httpGet:
                  path: /health
                  port: 8000
                initialDelaySeconds: 60
                periodSeconds: 15
                timeoutSeconds: 10
                failureThreshold: 5
              volumeMounts:
              - name: mlflow-artifacts
                mountPath: /mlflow/artifacts
            volumes:
            - name: mlflow-artifacts
              persistentVolumeClaim:
                claimName: mlflow-pvc

  # API Service - NodePort
  - target:
      kind: Service
      name: ml-pipeline-api-service
    patch: |-
      apiVersion: v1
      kind: Service
      metadata:
        name: ml-pipeline-api-service
      spec:
        type: NodePort
        ports:
        - name: http
          port: 8000
          targetPort: 8000
          protocol: TCP
          nodePort: ${NODEPORT_API}

  # Disable HPA (single replica)
  - target:
      kind: HorizontalPodAutoscaler
      name: ml-pipeline-api-hpa
    patch: |-
      apiVersion: autoscaling/v2
      kind: HorizontalPodAutoscaler
      metadata:
        name: ml-pipeline-api-hpa
      spec:
        minReplicas: 1
        maxReplicas: 1

  # Grafana Service - NodePort
  - target:
      kind: Service
      name: grafana-service
    patch: |-
      apiVersion: v1
      kind: Service
      metadata:
        name: grafana-service
      spec:
        type: NodePort
        ports:
        - port: 3000
          targetPort: 3000
          nodePort: ${NODEPORT_GRAFANA}

  # Prometheus Service - NodePort
  - target:
      kind: Service
      name: prometheus-service
    patch: |-
      apiVersion: v1
      kind: Service
      metadata:
        name: prometheus-service
      spec:
        type: NodePort
        ports:
        - port: 9090
          targetPort: 9090
          nodePort: ${NODEPORT_PROMETHEUS}

  # Prometheus - minimal resources
  - target:
      kind: Deployment
      name: prometheus
    patch: |-
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: prometheus
      spec:
        template:
          spec:
            containers:
            - name: prometheus
              resources:
                requests:
                  memory: "128Mi"
                  cpu: "50m"
                limits:
                  memory: "256Mi"
                  cpu: "250m"

  # Grafana - minimal resources
  - target:
      kind: Deployment
      name: grafana
    patch: |-
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: grafana
      spec:
        template:
          spec:
            containers:
            - name: grafana
              resources:
                requests:
                  memory: "64Mi"
                  cpu: "25m"
                limits:
                  memory: "128Mi"
                  cpu: "100m"
KUSTOMIZE_EOF

chown -R ubuntu:ubuntu $OVERLAY_DIR

# =============================================================================
# 7. Deploy to K3s
# =============================================================================
echo "[7/7] Deploying to Kubernetes..."

# Apply the manifests
cd /home/ubuntu/rt-ml-multicloud-platform
k3s kubectl apply -k ops/k8s/overlays/terraform-demo

# Wait for pods to be ready (with timeout)
echo "Waiting for pods to start (this may take several minutes)..."
sleep 60

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
echo "Service URLs:"
echo "  - MLflow:     http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4):${NODEPORT_MLFLOW}"
echo "  - API:        http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4):${NODEPORT_API}"
echo "  - Grafana:    http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4):${NODEPORT_GRAFANA}"
echo "  - Prometheus: http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4):${NODEPORT_PROMETHEUS}"
echo ""
echo "Check pod status with: sudo k3s kubectl get pods -n ml-pipeline"
echo ""
