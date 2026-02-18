# Near-Zero Cost EC2 Deployment Guide

This guide explains how to deploy the platform on a single AWS EC2 instance using **K3s** (Lightweight Kubernetes). This method avoids the EKS control plane cost (~$73/month) and only costs the EC2 run time (pennies per hour with Spot Instances).

## Prerequisites

- AWS Account
- AWS CLI configured locally (optional, for launching instance)
- SSH Client

## 1. Launch EC2 Instance

```bash
# Make script executable
chmod +x scripts/provision_ec2.sh

# Run script
./scripts/provision_ec2.sh
```

This will output the **Public IP** and create a key pair file `ml-pipeline-key.pem` if one doesn't exist.

## 2. Connect to Instance

```bash
ssh -i <your-key.pem> ubuntu@<ec2-public-ip>
```

## 3. Clone Repository

```bash
git clone https://github.com/ItaloPinheiro/rt-ml-multicloud-platform.git
cd rt-ml-multicloud-platform
```

## 4. Run Deployment Script

We have provided a script to automate the installation of Docker, K3s, and the application deployment.

```bash
# Make script executable
chmod +x scripts/deploy_ec2_k3s.sh

# Run script (it will ask for sudo password if needed)
./scripts/deploy_ec2_k3s.sh
```

**What the script does:**
1.  Installs Docker Engine.
2.  Installs K3s (Lightweight Kubernetes).
3.  Builds the Docker images locally (saving ECR costs).
4.  Imports images into K3s containerd.
5.  Applies Kubernetes manifests with a local configuration.

## 5. Access the Application

Once the script finishes, wait a few minutes for pods to start.

Check status:
```bash
kubectl get pods -n ml-pipeline-prod
```

Access the services using the **Public IP** of your EC2 instance and the NodePorts:

- **Model API**: `http://<EC2_PUBLIC_IP>:30001/docs` (Verify NodePort config)
- **MLflow**: `http://<EC2_PUBLIC_IP>:30000`

## 6. Cleanup

**Terminate the instance** when you are done to stop all costs.

```bash
# Via CLI
aws ec2 terminate-instances --instance-ids <instance-id>
```
