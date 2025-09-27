# Deployment Guide

This guide covers deployment options for the ML Pipeline Platform across different environments and cloud providers.

## 🏗️ Deployment Architecture

### Local Development
- Docker Compose for all services
- Local file storage for models and artifacts
- SQLite for development database

### Staging Environment
- Kubernetes cluster (single-zone)
- Cloud databases (managed PostgreSQL, Redis)
- Object storage for artifacts
- Basic monitoring and alerting

### Production Environment
- Multi-zone Kubernetes cluster
- High-availability databases with replicas
- Distributed object storage
- Comprehensive monitoring, logging, and alerting
- Auto-scaling and load balancing

## 🐳 Docker Compose Deployment

### Development Setup

```bash
# Clone repository
git clone https://github.com/your-org/rt-ml-multicloud-platform.git
cd rt-ml-multicloud-platform

# Setup environment
cp .env.example .env
# Edit .env with your configuration

# Start services
docker-compose up -d

# Verify deployment
./scripts/health-check.sh
```

### Production Docker Compose

```bash
# Use production configuration
docker-compose -f docker-compose.prod.yml up -d

# Scale API services
docker-compose -f docker-compose.prod.yml up -d --scale api=3

# Monitor logs
docker-compose logs -f api
```

## ☸️ Kubernetes Deployment

### Prerequisites

- Kubernetes cluster (1.24+)
- kubectl configured
- Helm (optional, for advanced deployments)

### Basic Deployment

```bash
# Deploy base configuration
kubectl apply -k k8s/base/

# Wait for services to be ready
kubectl wait --for=condition=available --timeout=300s deployment/ml-pipeline-api -n ml-pipeline

# Check pod status
kubectl get pods -n ml-pipeline
```

### Production Deployment

```bash
# Deploy production overlay
kubectl apply -k k8s/overlays/production/

# Monitor deployment
kubectl rollout status deployment/ml-pipeline-api -n ml-pipeline

# Scale if needed
kubectl scale deployment ml-pipeline-api --replicas=10 -n ml-pipeline
```

### Monitoring Deployment Status

```bash
# Check all resources
kubectl get all -n ml-pipeline

# View events
kubectl get events -n ml-pipeline --sort-by='.lastTimestamp'

# Check logs
kubectl logs -f deployment/ml-pipeline-api -n ml-pipeline
```

## 🌩️ Cloud Provider Deployments

### Google Cloud Platform (GCP)

#### Automated Setup

```bash
# Run GCP bootstrap script
./scripts/bootstrap/gcp-setup.sh

# Follow the generated configuration
# Update k8s/overlays/production/secrets.yaml with actual values

# Deploy to GKE
gcloud container clusters get-credentials ml-pipeline-cluster --zone=us-central1-a
kubectl apply -k k8s/overlays/production/
```

#### Manual GCP Setup

1. **Create GKE Cluster**
```bash
gcloud container clusters create ml-pipeline-cluster \
  --zone=us-central1-a \
  --machine-type=e2-standard-4 \
  --num-nodes=3 \
  --enable-autoscaling \
  --min-nodes=3 \
  --max-nodes=10
```

2. **Create Cloud SQL Instance**
```bash
gcloud sql instances create ml-pipeline-postgres \
  --database-version=POSTGRES_15 \
  --tier=db-custom-2-4096 \
  --region=us-central1
```

3. **Create Redis Instance**
```bash
gcloud redis instances create ml-pipeline-redis \
  --size=1 \
  --region=us-central1
```

4. **Deploy Application**
```bash
kubectl apply -k k8s/overlays/production/
```

### Amazon Web Services (AWS)

#### Automated Setup

```bash
# Run AWS bootstrap script
./scripts/bootstrap/aws-setup.sh

# Update configuration with actual endpoints
# Deploy to EKS
aws eks update-kubeconfig --region us-east-1 --name ml-pipeline-cluster
kubectl apply -k k8s/overlays/production/
```

#### Manual AWS Setup

1. **Create EKS Cluster**
```bash
eksctl create cluster \
  --name ml-pipeline-cluster \
  --region us-east-1 \
  --nodegroup-name ml-pipeline-nodes \
  --nodes 3 \
  --nodes-min 3 \
  --nodes-max 10
```

2. **Create RDS Instance**
```bash
aws rds create-db-instance \
  --db-instance-identifier ml-pipeline-postgres \
  --db-instance-class db.t3.medium \
  --engine postgres \
  --master-username ml_admin \
  --master-user-password YOUR_PASSWORD \
  --allocated-storage 50
```

3. **Create ElastiCache Redis**
```bash
aws elasticache create-cache-cluster \
  --cache-cluster-id ml-pipeline-redis \
  --cache-node-type cache.t3.medium \
  --engine redis \
  --num-cache-nodes 1
```

### Microsoft Azure

#### Azure Kubernetes Service (AKS)

```bash
# Create resource group
az group create --name ml-pipeline-rg --location eastus

# Create AKS cluster
az aks create \
  --resource-group ml-pipeline-rg \
  --name ml-pipeline-cluster \
  --node-count 3 \
  --enable-addons monitoring \
  --generate-ssh-keys

# Get credentials
az aks get-credentials --resource-group ml-pipeline-rg --name ml-pipeline-cluster

# Deploy application
kubectl apply -k k8s/overlays/production/
```

## 🔐 Security Configuration

### SSL/TLS Certificates

#### Using cert-manager

```bash
# Install cert-manager
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml

# Create cluster issuer
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: your-email@company.com
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
    - http01:
        ingress:
          class: nginx
EOF

# TLS will be automatically configured for ingress resources
```

### Secrets Management

#### Using Kubernetes Secrets

```bash
# Create secrets from files
kubectl create secret generic ml-pipeline-secrets \
  --from-file=database-password.txt \
  --from-file=redis-password.txt \
  --from-file=gcp-service-account.json \
  -n ml-pipeline
```

#### Using External Secrets Operator

```bash
# Install external-secrets
helm repo add external-secrets https://charts.external-secrets.io
helm install external-secrets external-secrets/external-secrets -n external-secrets-system --create-namespace

# Configure secret store (example for AWS Secrets Manager)
kubectl apply -f - <<EOF
apiVersion: external-secrets.io/v1beta1
kind: SecretStore
metadata:
  name: aws-secrets-manager
  namespace: ml-pipeline
spec:
  provider:
    aws:
      service: SecretsManager
      region: us-east-1
      auth:
        jwt:
          serviceAccountRef:
            name: external-secrets-sa
EOF
```

## 📊 Monitoring and Observability

### Prometheus and Grafana

```bash
# Install Prometheus Operator
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install prometheus prometheus-community/kube-prometheus-stack -n monitoring --create-namespace

# Access Grafana (default admin/prom-operator)
kubectl port-forward svc/prometheus-grafana 3000:80 -n monitoring
```

### Logging with ELK Stack

```bash
# Install Elasticsearch
helm repo add elastic https://helm.elastic.co
helm install elasticsearch elastic/elasticsearch -n logging --create-namespace

# Install Kibana
helm install kibana elastic/kibana -n logging

# Install Filebeat
helm install filebeat elastic/filebeat -n logging
```

### Distributed Tracing with Jaeger

```bash
# Install Jaeger Operator
kubectl create namespace observability
kubectl create -f https://github.com/jaegertracing/jaeger-operator/releases/download/v1.47.0/jaeger-operator.yaml -n observability

# Deploy Jaeger instance
kubectl apply -f - <<EOF
apiVersion: jaegertracing.io/v1
kind: Jaeger
metadata:
  name: ml-pipeline-tracing
  namespace: ml-pipeline
spec:
  strategy: production
  storage:
    type: elasticsearch
    options:
      es.server-urls: http://elasticsearch:9200
EOF
```

## 🚀 Scaling and Performance

### Horizontal Pod Autoscaling

```bash
# Enable metrics server (if not already enabled)
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# HPA is already configured in k8s/base/api.yaml
# Monitor HPA status
kubectl get hpa -n ml-pipeline
kubectl describe hpa ml-pipeline-api-hpa -n ml-pipeline
```

### Vertical Pod Autoscaling

```bash
# Install VPA (if using GKE)
gcloud container clusters update ml-pipeline-cluster --enable-vertical-pod-autoscaling --zone=us-central1-a

# Create VPA resource
kubectl apply -f - <<EOF
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: ml-pipeline-api-vpa
  namespace: ml-pipeline
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: ml-pipeline-api
  updatePolicy:
    updateMode: "Auto"
EOF
```

### Cluster Autoscaling

#### GKE
```bash
# Enable cluster autoscaling
gcloud container clusters update ml-pipeline-cluster \
  --enable-autoscaling \
  --min-nodes=3 \
  --max-nodes=50 \
  --zone=us-central1-a
```

#### EKS
```bash
# Deploy cluster autoscaler
kubectl apply -f https://raw.githubusercontent.com/kubernetes/autoscaler/master/cluster-autoscaler/cloudprovider/aws/examples/cluster-autoscaler-autodiscover.yaml

# Edit deployment to add cluster name
kubectl -n kube-system edit deployment.apps/cluster-autoscaler
# Add --node-group-auto-discovery=asg:tag=k8s.io/cluster-autoscaler/enabled,k8s.io/cluster-autoscaler/ml-pipeline-cluster
```

## 🔄 CI/CD Pipeline Integration

### GitHub Actions

```yaml
# .github/workflows/deploy.yml
name: Deploy to Production

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3

    - name: Configure kubectl
      uses: azure/k8s-set-context@v1
      with:
        method: kubeconfig
        kubeconfig: ${{ secrets.KUBE_CONFIG }}

    - name: Deploy to Kubernetes
      run: |
        kubectl apply -k k8s/overlays/production/
        kubectl rollout status deployment/ml-pipeline-api -n ml-pipeline
```

### GitLab CI

```yaml
# .gitlab-ci.yml
deploy:
  stage: deploy
  image: bitnami/kubectl
  script:
    - kubectl config set-cluster k8s --server="$KUBE_URL" --insecure-skip-tls-verify=true
    - kubectl config set-credentials gitlab --token="$KUBE_TOKEN"
    - kubectl config set-context default --cluster=k8s --user=gitlab
    - kubectl config use-context default
    - kubectl apply -k k8s/overlays/production/
  only:
    - main
```

## 🧪 Testing Deployments

### Health Checks

```bash
# Check service health
kubectl exec -it deployment/ml-pipeline-api -n ml-pipeline -- curl http://localhost:8000/health

# Check database connectivity
kubectl exec -it deployment/postgres -n ml-pipeline -- psql -U postgres -c "SELECT 1;"

# Check Redis connectivity
kubectl exec -it deployment/redis -n ml-pipeline -- redis-cli ping
```

### Load Testing

```bash
# Install load testing tools
kubectl create namespace load-testing
kubectl run load-test --image=fortio/fortio --restart=Never -n load-testing -- load -qps 100 -t 60s -c 10 http://ml-pipeline-api-service.ml-pipeline:8000/health

# Monitor during load test
kubectl logs load-test -n load-testing
kubectl top pods -n ml-pipeline
```

### Smoke Tests

```bash
# Run smoke tests after deployment
python scripts/smoke_tests.py --endpoint http://your-api-endpoint.com
```

## 🆘 Troubleshooting

### Common Issues

#### Pod Stuck in Pending State
```bash
# Check events
kubectl describe pod POD_NAME -n ml-pipeline

# Check resource availability
kubectl top nodes
kubectl describe nodes

# Check persistent volume claims
kubectl get pvc -n ml-pipeline
```

#### Service Not Accessible
```bash
# Check service and endpoints
kubectl get svc,endpoints -n ml-pipeline

# Check ingress configuration
kubectl describe ingress ml-pipeline-api-ingress -n ml-pipeline

# Test internal connectivity
kubectl run debug --image=curlimages/curl -it --rm --restart=Never -- curl http://ml-pipeline-api-service:8000/health
```

#### Database Connection Issues
```bash
# Check database pod logs
kubectl logs deployment/postgres -n ml-pipeline

# Test database connection
kubectl exec -it deployment/ml-pipeline-api -n ml-pipeline -- python -c "
from src.database.session import DatabaseManager
from src.utils.config import get_config
config = get_config()
db = DatabaseManager(config.database)
db.initialize()
print('Connected:', db.check_connection())
"
```

### Rollback Procedures

```bash
# Check deployment history
kubectl rollout history deployment/ml-pipeline-api -n ml-pipeline

# Rollback to previous version
kubectl rollout undo deployment/ml-pipeline-api -n ml-pipeline

# Rollback to specific revision
kubectl rollout undo deployment/ml-pipeline-api --to-revision=2 -n ml-pipeline

# Monitor rollback
kubectl rollout status deployment/ml-pipeline-api -n ml-pipeline
```

## 📋 Deployment Checklist

### Pre-Deployment
- [ ] Configuration files updated
- [ ] Secrets properly configured
- [ ] Database migrations ready
- [ ] Container images built and pushed
- [ ] Monitoring dashboards configured

### Deployment
- [ ] Deploy in correct order (database → cache → API)
- [ ] Verify each service starts successfully
- [ ] Run smoke tests
- [ ] Check monitoring alerts
- [ ] Verify external connectivity

### Post-Deployment
- [ ] Monitor application metrics
- [ ] Check error logs
- [ ] Verify data pipeline functionality
- [ ] Test critical user journeys
- [ ] Update documentation

---

For additional support, see [troubleshooting guide](./troubleshooting.md) or [open an issue](https://github.com/your-org/rt-ml-multicloud-platform/issues).