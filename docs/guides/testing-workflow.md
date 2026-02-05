# Comprehensive Testing & Deployment Guide

This guide outlines the three distinct methods for running and testing the platform, ranging from local development to cloud deployment.

## Summary of Methods

| Method | Environment | Primary Use Case | Key Command |
|--------|-------------|------------------|-------------|
| **1. Logic Demo** | Docker Compose | rapid development, functional testing, end-to-end logic verification. | `./scripts/demo/demo.sh` |
| **2. Infrastructure Demo** | Local Kubernetes (Docker Desktop) | verifying K8s manifests, PVCs, NodePorts, and service discovery locally. | `./scripts/test_local_k8s.sh` |
| **3. Cloud Staging** | AWS EC2 (K3s) | production-like environment, public access, final validation. | `./scripts/deploy_ec2_k3s.sh` |

---

## Method 1: Local Logic Demo (Docker Compose)

**Objective:** Verify the *application logic* and end-to-end flow without the complexity of Kubernetes.

This method uses `docker-compose` to spin up the entire stack. It is the fastest way to iterate on code changes.

### How to Run
```bash
./scripts/demo/demo.sh
```

### What it does
1.  **Cleans** existing containers and volumes.
2.  **Starts** all services (API, MLflow, Redis, MinIO, etc.) defined in `docker-compose.yml`.
3.  **Executes** a training job via a `beam-runner` container.
4.  **Verifies** the model in MLflow and MinIO.
5.  **Tests** the API with sample predictions.
6.  **Simulates** a model update (trains v2) and checks auto-reloading.

### Access Points
- **API**: [http://localhost:8000](http://localhost:8000)
- **MLflow**: [http://localhost:5000](http://localhost:5000)
- **MinIO**: [http://localhost:9001](http://localhost:9001)

---

## Method 2: Infrastructure Demo (Local Kubernetes)

**Objective:** Verify the *deployment configuration* (manifests, networking, storage) locally.

This method uses Docker Desktop's Kubernetes cluster to mimic the production environment. It validates that your `krampus` (Kustomize) overlays and PVC configurations are correct.

### Prerequisites
- Docker Desktop with Kubernetes enabled.

### How to Run
**Step 1: Deploy Infrastructure**
```bash
./scripts/test_local_k8s.sh
```
*Builds docker images locally and applies `k8s/overlays/ec2-local`.*

**Step 2: Run Functional Test**
```bash
python scripts/demo/test_local_k8s_train.py
```
*Trains a model locally and pushes artifacts to the cluster's MLflow server, verifying the PVC mount fix.*

### Access Points (NodePorts)
- **API**: [http://localhost:30001](http://localhost:30001)
- **MLflow**: [http://localhost:30000](http://localhost:30000)
- **Grafana**: [http://localhost:30002](http://localhost:30002)
- **Prometheus**: [http://localhost:30090](http://localhost:30090)

---

## Method 3: Cloud Staging (AWS EC2)

**Objective:** Deploy to a live, zero-cost cloud environment for final staging.

This method provisions a `t3.medium` Spot Instance, installs K3s (lightweight Kubernetes), and deploys the stack.

### How to Run
**Step 1: Provision Infrastructure**
```bash
./scripts/provision_ec2.sh
```
*Launches an EC2 instance and returns its Public IP.*

**Step 2: Deploy Application**
```bash
# Connect to the instance and run the deployment script
./scripts/deploy_ec2_k3s.sh
```
*(Note: You may need to copy the script and source code to the instance first).*

### Access Points
- **API**: `http://<EC2-PUBLIC-IP>:30001`
- **MLflow**: `http://<EC2-PUBLIC-IP>:30000`
- **Grafana**: `http://<EC2-PUBLIC-IP>:30002`
