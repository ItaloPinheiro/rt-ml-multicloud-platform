#!/bin/bash

# GCP Bootstrap Script for ML Pipeline Platform
# This script sets up the necessary GCP resources for the ML pipeline

set -euo pipefail

# Configuration
PROJECT_ID="${GCP_PROJECT:-ml-pipeline-platform}"
REGION="${GCP_REGION:-us-central1}"
ZONE="${GCP_ZONE:-us-central1-a}"
CLUSTER_NAME="${GKE_CLUSTER_NAME:-ml-pipeline-cluster}"
SERVICE_ACCOUNT_NAME="${SERVICE_ACCOUNT_NAME:-ml-pipeline-sa}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if required tools are installed
check_prerequisites() {
    log_info "Checking prerequisites..."

    if ! command -v gcloud &> /dev/null; then
        log_error "gcloud CLI is not installed. Please install it first."
        exit 1
    fi

    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl is not installed. Please install it first."
        exit 1
    fi

    log_success "All prerequisites are satisfied"
}

# Authenticate and set project
setup_authentication() {
    log_info "Setting up GCP authentication..."

    # Check if already authenticated
    if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -n1 > /dev/null; then
        log_info "Please authenticate with GCP..."
        gcloud auth login
    fi

    # Set project
    gcloud config set project "$PROJECT_ID"

    # Enable billing if not already enabled
    log_info "Checking billing account..."
    if ! gcloud beta billing projects describe "$PROJECT_ID" --format="value(billingEnabled)" | grep -q "True"; then
        log_warning "Billing is not enabled for project $PROJECT_ID"
        log_info "Please enable billing in the GCP Console and re-run this script"
        exit 1
    fi

    log_success "Authentication and project setup complete"
}

# Enable required APIs
enable_apis() {
    log_info "Enabling required GCP APIs..."

    local apis=(
        "container.googleapis.com"
        "compute.googleapis.com"
        "pubsub.googleapis.com"
        "cloudsql.googleapis.com"
        "redis.googleapis.com"
        "storage.googleapis.com"
        "logging.googleapis.com"
        "monitoring.googleapis.com"
        "cloudresourcemanager.googleapis.com"
        "iam.googleapis.com"
        "artifactregistry.googleapis.com"
    )

    for api in "${apis[@]}"; do
        log_info "Enabling $api..."
        gcloud services enable "$api"
    done

    log_success "All required APIs enabled"
}

# Create service account
create_service_account() {
    log_info "Creating service account..."

    # Check if service account already exists
    if gcloud iam service-accounts describe "${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" &> /dev/null; then
        log_warning "Service account $SERVICE_ACCOUNT_NAME already exists"
    else
        gcloud iam service-accounts create "$SERVICE_ACCOUNT_NAME" \
            --display-name="ML Pipeline Service Account" \
            --description="Service account for ML Pipeline Platform"
        log_success "Service account created"
    fi

    # Grant necessary roles
    local roles=(
        "roles/pubsub.editor"
        "roles/storage.admin"
        "roles/cloudsql.client"
        "roles/redis.editor"
        "roles/monitoring.metricWriter"
        "roles/logging.logWriter"
        "roles/container.developer"
    )

    for role in "${roles[@]}"; do
        log_info "Granting role $role..."
        gcloud projects add-iam-policy-binding "$PROJECT_ID" \
            --member="serviceAccount:${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
            --role="$role"
    done

    # Create and download service account key
    local key_file="gcp-service-account-key.json"
    if [[ ! -f "$key_file" ]]; then
        gcloud iam service-accounts keys create "$key_file" \
            --iam-account="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
        log_success "Service account key created: $key_file"
        log_warning "Keep this key file secure and do not commit it to version control"
    fi
}

# Create GKE cluster
create_gke_cluster() {
    log_info "Creating GKE cluster..."

    # Check if cluster already exists
    if gcloud container clusters describe "$CLUSTER_NAME" --zone="$ZONE" &> /dev/null; then
        log_warning "GKE cluster $CLUSTER_NAME already exists"
    else
        gcloud container clusters create "$CLUSTER_NAME" \
            --zone="$ZONE" \
            --machine-type="e2-standard-4" \
            --num-nodes=3 \
            --enable-autoscaling \
            --min-nodes=3 \
            --max-nodes=10 \
            --enable-autorepair \
            --enable-autoupgrade \
            --disk-size=50GB \
            --disk-type=pd-ssd \
            --enable-network-policy \
            --enable-ip-alias \
            --workload-pool="${PROJECT_ID}.svc.id.goog" \
            --addons=HorizontalPodAutoscaling,HttpLoadBalancing,GcePersistentDiskCsiDriver

        log_success "GKE cluster created"
    fi

    # Get cluster credentials
    gcloud container clusters get-credentials "$CLUSTER_NAME" --zone="$ZONE"

    # Create namespace
    kubectl create namespace ml-pipeline --dry-run=client -o yaml | kubectl apply -f -

    log_success "GKE cluster configured"
}

# Create Cloud SQL instance
create_cloud_sql() {
    log_info "Creating Cloud SQL instance..."

    local instance_name="ml-pipeline-postgres"

    # Check if instance already exists
    if gcloud sql instances describe "$instance_name" &> /dev/null; then
        log_warning "Cloud SQL instance $instance_name already exists"
    else
        gcloud sql instances create "$instance_name" \
            --database-version=POSTGRES_15 \
            --tier=db-custom-2-4096 \
            --region="$REGION" \
            --storage-type=SSD \
            --storage-size=50GB \
            --storage-auto-increase \
            --backup-start-time=03:00 \
            --enable-bin-log \
            --maintenance-window-day=SUN \
            --maintenance-window-hour=04

        log_success "Cloud SQL instance created"
    fi

    # Create database
    gcloud sql databases create ml_pipeline --instance="$instance_name" || true

    # Create user
    gcloud sql users create ml_user --instance="$instance_name" --password=$(openssl rand -base64 32) || true

    log_success "Cloud SQL configured"
}

# Create Redis instance
create_redis() {
    log_info "Creating Redis instance..."

    local instance_name="ml-pipeline-redis"

    # Check if instance already exists
    if gcloud redis instances describe "$instance_name" --region="$REGION" &> /dev/null; then
        log_warning "Redis instance $instance_name already exists"
    else
        gcloud redis instances create "$instance_name" \
            --size=1 \
            --region="$REGION" \
            --redis-version=redis_7_0 \
            --tier=basic

        log_success "Redis instance created"
    fi
}

# Create Pub/Sub topics
create_pubsub_topics() {
    log_info "Creating Pub/Sub topics..."

    local topics=(
        "ml-pipeline-transactions"
        "ml-pipeline-features"
        "ml-pipeline-predictions"
        "ml-pipeline-monitoring"
    )

    for topic in "${topics[@]}"; do
        if gcloud pubsub topics describe "$topic" &> /dev/null; then
            log_warning "Topic $topic already exists"
        else
            gcloud pubsub topics create "$topic"
            log_success "Created topic: $topic"
        fi

        # Create subscription
        local subscription="${topic}-subscription"
        if gcloud pubsub subscriptions describe "$subscription" &> /dev/null; then
            log_warning "Subscription $subscription already exists"
        else
            gcloud pubsub subscriptions create "$subscription" --topic="$topic"
            log_success "Created subscription: $subscription"
        fi
    done
}

# Create storage buckets
create_storage_buckets() {
    log_info "Creating storage buckets..."

    local buckets=(
        "${PROJECT_ID}-ml-artifacts"
        "${PROJECT_ID}-ml-models"
        "${PROJECT_ID}-ml-data"
        "${PROJECT_ID}-ml-backups"
    )

    for bucket in "${buckets[@]}"; do
        if gsutil ls -b "gs://$bucket" &> /dev/null; then
            log_warning "Bucket $bucket already exists"
        else
            gsutil mb -l "$REGION" "gs://$bucket"
            # Set lifecycle policy for backups bucket
            if [[ "$bucket" == *"backups"* ]]; then
                cat > lifecycle.json << EOF
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "Delete"},
        "condition": {"age": 90}
      }
    ]
  }
}
EOF
                gsutil lifecycle set lifecycle.json "gs://$bucket"
                rm lifecycle.json
            fi
            log_success "Created bucket: $bucket"
        fi
    done
}

# Create Artifact Registry
create_artifact_registry() {
    log_info "Creating Artifact Registry..."

    local repo_name="ml-pipeline"

    if gcloud artifacts repositories describe "$repo_name" --location="$REGION" &> /dev/null; then
        log_warning "Artifact Registry repository $repo_name already exists"
    else
        gcloud artifacts repositories create "$repo_name" \
            --repository-format=docker \
            --location="$REGION" \
            --description="ML Pipeline Docker images"

        log_success "Artifact Registry repository created"
    fi

    # Configure Docker authentication
    gcloud auth configure-docker "${REGION}-docker.pkg.dev"
}

# Setup monitoring
setup_monitoring() {
    log_info "Setting up monitoring..."

    # Create notification channel (example for email)
    # This requires manual setup in the console or additional API calls
    log_info "Please set up notification channels in the GCP Console for alerting"

    log_success "Basic monitoring setup complete"
}

# Generate deployment configuration
generate_deployment_config() {
    log_info "Generating deployment configuration..."

    cat > gcp-deployment-config.yaml << EOF
# GCP Deployment Configuration
project_id: $PROJECT_ID
region: $REGION
zone: $ZONE
cluster_name: $CLUSTER_NAME

# Service endpoints (replace with actual values after creation)
services:
  postgres:
    host: "REPLACE_WITH_CLOUD_SQL_IP"
    port: 5432
    database: "ml_pipeline"
    user: "ml_user"

  redis:
    host: "REPLACE_WITH_REDIS_IP"
    port: 6379

  pubsub:
    project: $PROJECT_ID
    topics:
      - ml-pipeline-transactions
      - ml-pipeline-features
      - ml-pipeline-predictions
      - ml-pipeline-monitoring

  storage:
    artifacts_bucket: "${PROJECT_ID}-ml-artifacts"
    models_bucket: "${PROJECT_ID}-ml-models"
    data_bucket: "${PROJECT_ID}-ml-data"
    backups_bucket: "${PROJECT_ID}-ml-backups"

  artifact_registry:
    location: $REGION
    repository: ml-pipeline

# Kubernetes configuration
kubernetes:
  namespace: ml-pipeline
  service_account: $SERVICE_ACCOUNT_NAME
EOF

    log_success "Deployment configuration saved to gcp-deployment-config.yaml"
}

# Main execution
main() {
    log_info "Starting GCP setup for ML Pipeline Platform..."
    log_info "Project: $PROJECT_ID"
    log_info "Region: $REGION"
    log_info "Zone: $ZONE"

    check_prerequisites
    setup_authentication
    enable_apis
    create_service_account
    create_gke_cluster
    create_cloud_sql
    create_redis
    create_pubsub_topics
    create_storage_buckets
    create_artifact_registry
    setup_monitoring
    generate_deployment_config

    log_success "GCP setup completed successfully!"
    log_info "Next steps:"
    log_info "1. Update the IP addresses in gcp-deployment-config.yaml"
    log_info "2. Update Kubernetes secrets with actual values"
    log_info "3. Deploy the application using: kubectl apply -k ops/k8s/overlays/production"
    log_info "4. Configure monitoring dashboards and alerts"
}

# Show help
if [[ "${1:-}" == "--help" ]] || [[ "${1:-}" == "-h" ]]; then
    cat << EOF
GCP Bootstrap Script for ML Pipeline Platform

Usage: $0 [OPTIONS]

Environment Variables:
  GCP_PROJECT              GCP Project ID (default: ml-pipeline-platform)
  GCP_REGION              GCP Region (default: us-central1)
  GCP_ZONE                GCP Zone (default: us-central1-a)
  GKE_CLUSTER_NAME        GKE Cluster name (default: ml-pipeline-cluster)
  SERVICE_ACCOUNT_NAME    Service account name (default: ml-pipeline-sa)

Examples:
  # Use defaults
  $0

  # Use custom project
  GCP_PROJECT=my-ml-project $0

  # Use custom region and zone
  GCP_REGION=europe-west1 GCP_ZONE=europe-west1-b $0

This script will:
1. Enable required GCP APIs
2. Create service accounts and IAM bindings
3. Create GKE cluster
4. Create Cloud SQL PostgreSQL instance
5. Create Redis instance
6. Create Pub/Sub topics and subscriptions
7. Create storage buckets
8. Create Artifact Registry repository
9. Generate deployment configuration

Prerequisites:
- gcloud CLI installed and configured
- kubectl installed
- Billing enabled for the GCP project
EOF
    exit 0
fi

# Run main function
main "$@"