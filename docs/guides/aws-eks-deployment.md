# AWS EKS Deployment Guide

This guide details the steps to deploy the RT ML Multicloud Platform to Amazon Elastic Kubernetes Service (EKS).

## Prerequisites

Ensure you have the following tools installed and configured:

1.  **AWS CLI**: [Install & Configure](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
    ```bash
    aws configure
    ```
2.  **eksctl**: [Install](https://eksctl.io/introduction/#installation) (The official CLI for Amazon EKS)
3.  **kubectl**: [Install](https://kubernetes.io/docs/tasks/tools/)
4.  **Docker**: [Install](https://docs.docker.com/get-docker/)

## 1. Create EKS Cluster

Create a managed Kubernetes cluster using `eksctl`. This will provision the VPC, subnets, and worker nodes.

```bash
eksctl create cluster \
  --name rt-ml-cluster \
  --region us-east-1 \
  --nodegroup-name spot-workers \
  --node-type t3.medium \
  --nodes 2 \
  --nodes-min 1 \
  --nodes-max 3 \
  --managed \
  --spot
```

> [!IMPORTANT]
> **Cost Warning**: EKS charges **$0.10 per hour** (~$73/month) for the control plane, even if you use free tier nodes. To minimize costs:
> 1.  **Delete the cluster immediately** after your demo.
> 2.  Use **Spot Instances** (configured above) to save up to 90% on compute.
> 3.  If you need a **truly zero-cost** option (excluding EC2 run time), consider running [Minikube](https://minikube.sigs.k8s.io/docs/start/) or [K3s](https://k3s.io/) on a single EC2 instance instead of using managed EKS.

*Note: This process can take 15-20 minutes.*

Once completed, `eksctl` will automatically update your `~/.kube/config` file. Verify connectivity:

```bash
kubectl get nodes
```

## 2. S3 Bucket Setup

MLflow requires an S3 bucket to store model artifacts.

```bash
# Create a unique bucket name
BUCKET_NAME=mlflow-artifacts-$(date +%s)
aws s3 mb s3://$BUCKET_NAME --region us-east-1

# Enable versioning (recommended for model lineage)
aws s3api put-bucket-versioning --bucket $BUCKET_NAME --versioning-configuration Status=Enabled

echo "Your MLflow Artifact Bucket: $BUCKET_NAME"
```

## 3. Container Registry (ECR) Setup

You need to host your Docker images in Amazon Elastic Container Registry (ECR).

### 3.1 Create Repositories

```bash
aws ecr create-repository --repository-name ml-pipeline/api
aws ecr create-repository --repository-name ml-pipeline/mlflow
aws ecr create-repository --repository-name ml-pipeline/beam-runner
```

### 3.2 Login to ECR

Replace `<aws_account_id>` and `<region>` with your values.

```bash
aws ecr get-login-password --region <region> | docker login --username AWS --password-stdin <aws_account_id>.dkr.ecr.<region>.amazonaws.com
```

### 3.3 Build and Push Images

**Model API:**
```bash
docker build -t <aws_account_id>.dkr.ecr.<region>.amazonaws.com/ml-pipeline/api:v1.0.0 -f docker/api/Dockerfile .
docker push <aws_account_id>.dkr.ecr.<region>.amazonaws.com/ml-pipeline/api:v1.0.0
```

**MLflow Server:**
```bash
docker build -t <aws_account_id>.dkr.ecr.<region>.amazonaws.com/ml-pipeline/mlflow:v1.0.0 -f docker/mlflow/Dockerfile .
docker push <aws_account_id>.dkr.ecr.<region>.amazonaws.com/ml-pipeline/mlflow:v1.0.0
```

## 4. Configure Kubernetes Manifests

You need to update the Kustomize configuration to use your ECR images.

Edit `k8s/overlays/production/kustomization.yaml`:

```yaml
images:
- name: ml-pipeline/api
  newName: <aws_account_id>.dkr.ecr.<region>.amazonaws.com/ml-pipeline/api
  newTag: v1.0.0
- name: ml-pipeline/mlflow
  newName: <aws_account_id>.dkr.ecr.<region>.amazonaws.com/ml-pipeline/mlflow
  newTag: v1.0.0
```

## 5. Secrets Management

Create Kubernetes secrets for sensitive data. Avoid committing these to Git.

```bash
# Database Credentials
kubectl create secret generic ml-pipeline-secrets \
  --from-literal=POSTGRES_PASSWORD=your_secure_db_password \
  --from-literal=POSTGRES_USER=mlflow \
  --from-literal=POSTGRES_DB=mlflow \
  --from-literal=REDIS_PASSWORD=your_secure_redis_password \
  --namespace=ml-pipeline-prod

# AWS Credentials (for MLflow artifact access)
# Ensure these credentials have read/write access to the S3 bucket created in Step 2
kubectl create secret generic aws-credentials \
  --from-literal=AWS_ACCESS_KEY_ID=your_access_key \
  --from-literal=AWS_SECRET_ACCESS_KEY=your_secret_key \
  --namespace=ml-pipeline-prod
```

*Note: Ensure the `ml-pipeline-prod` namespace exists or let Kustomize create it.*

## 6. Deploy to EKS

Apply the production overlay using Kustomize:

```bash
kubectl apply -k k8s/overlays/production
```

## 7. Accessing Services

### Check Status
```bash
kubectl get pods -n ml-pipeline-prod
```

### Expose Services
The default configuration might use `ClusterIP`. To access services externally (e.g., the API), you can change the service type to `LoadBalancer` or use `kubectl port-forward` for testing.

**Port Forwarding (Testing):**
```bash
kubectl port-forward svc/model-api 8000:8000 -n ml-pipeline-prod
```
Now access at `http://localhost:8000/docs`.

**LoadBalancer (Production):**
Ensure your `k8s/base/api.yaml` (or overlay) defines the service type as `LoadBalancer`.

```bash
kubectl get svc -n ml-pipeline-prod
```
Look for the `EXTERNAL-IP` (it will be an AWS ELB DNS name).

## 8. Production Considerations

For a robust production environment, consider replacing in-cluster stateful services with AWS Managed Services:

1.  **Database**: Use **Amazon RDS for PostgreSQL** instead of the `mlflow-db` container.
    *   Update `POSTGRES_HOST` in your secrets to point to the RDS endpoint.
2.  **Caching**: Use **Amazon ElastiCache for Redis** instead of the `redis` container.
    *   Update `REDIS_HOST` in your secrets.
3.  **Streaming**: Use **Amazon MSK (Managed Streaming for Apache Kafka)** instead of the `kafka` and `zookeeper` containers.
    *   Update `KAFKA_BOOTSTRAP_SERVERS` to point to MSK brokers.
4.  **IAM Roles for Service Accounts (IRSA)**: Instead of long-lived AWS keys in secrets (`aws-credentials`), configure IRSA to grant the MLflow pod permissions to access S3 securely.

## 9. Alternative: Zero-Cost Demo on EC2

To avoid the EKS control plane cost (~$0.10/hour), you can run a single EC2 instance with `k3s`.

1.  **Launch Instance**:
    *   Type: `t3.large` (Spot Instance recommended for lowest cost).
    *   AMI: Ubuntu 22.04 LTS.
    *   Security Group: Allow ports 22 (SSH), 80/443 (HTTP/HTTPS), 6443 (K8s API), 30000-32767 (NodePorts).

2.  **Install k3s**:
    ```bash
    curl -sfL https://get.k3s.io | sh -
    # Copy config to default location
    mkdir -p ~/.kube
    sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
    sudo chown $USER:$USER ~/.kube/config
    ```

3.  **Deploy**:
    *   Clone your repo.
    *   Build images locally or pull from ECR.
    *   Apply manifests: `kubectl apply -k k8s/overlays/production`

This method only costs the EC2 run time (pennies per hour with Spot).

## 10. Cleanup

To avoid incurring costs, delete the cluster when not in use:

```bash
eksctl delete cluster --name rt-ml-cluster --region us-east-1
```
