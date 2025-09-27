#!/bin/bash

# AWS Bootstrap Script for ML Pipeline Platform
# This script sets up the necessary AWS resources for the ML pipeline

set -euo pipefail

# Configuration
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${EKS_CLUSTER_NAME:-ml-pipeline-cluster}"
VPC_NAME="${VPC_NAME:-ml-pipeline-vpc}"
DB_INSTANCE_IDENTIFIER="${DB_INSTANCE_IDENTIFIER:-ml-pipeline-postgres}"
REDIS_CLUSTER_ID="${REDIS_CLUSTER_ID:-ml-pipeline-redis}"
S3_BUCKET_PREFIX="${S3_BUCKET_PREFIX:-ml-pipeline}"

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

    if ! command -v aws &> /dev/null; then
        log_error "AWS CLI is not installed. Please install it first."
        exit 1
    fi

    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl is not installed. Please install it first."
        exit 1
    fi

    if ! command -v eksctl &> /dev/null; then
        log_error "eksctl is not installed. Please install it first."
        exit 1
    fi

    # Check AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        log_error "AWS credentials not configured. Please run 'aws configure' first."
        exit 1
    fi

    log_success "All prerequisites are satisfied"
}

# Set AWS region
setup_region() {
    log_info "Setting AWS region to $AWS_REGION..."
    aws configure set region "$AWS_REGION"
    log_success "AWS region configured"
}

# Create VPC and networking
create_vpc() {
    log_info "Creating VPC and networking..."

    # Check if VPC already exists
    local vpc_id
    vpc_id=$(aws ec2 describe-vpcs --filters "Name=tag:Name,Values=$VPC_NAME" --query 'Vpcs[0].VpcId' --output text 2>/dev/null || echo "None")

    if [[ "$vpc_id" != "None" ]]; then
        log_warning "VPC $VPC_NAME already exists with ID: $vpc_id"
        echo "$vpc_id" > vpc-id.txt
        return
    fi

    # Create VPC
    vpc_id=$(aws ec2 create-vpc \
        --cidr-block 10.0.0.0/16 \
        --query 'Vpc.VpcId' \
        --output text)

    aws ec2 create-tags \
        --resources "$vpc_id" \
        --tags Key=Name,Value="$VPC_NAME"

    # Enable DNS hostnames
    aws ec2 modify-vpc-attribute \
        --vpc-id "$vpc_id" \
        --enable-dns-hostnames

    # Create Internet Gateway
    local igw_id
    igw_id=$(aws ec2 create-internet-gateway \
        --query 'InternetGateway.InternetGatewayId' \
        --output text)

    aws ec2 attach-internet-gateway \
        --vpc-id "$vpc_id" \
        --internet-gateway-id "$igw_id"

    # Create subnets
    local public_subnet_1
    local public_subnet_2
    local private_subnet_1
    local private_subnet_2

    public_subnet_1=$(aws ec2 create-subnet \
        --vpc-id "$vpc_id" \
        --cidr-block 10.0.1.0/24 \
        --availability-zone "${AWS_REGION}a" \
        --query 'Subnet.SubnetId' \
        --output text)

    public_subnet_2=$(aws ec2 create-subnet \
        --vpc-id "$vpc_id" \
        --cidr-block 10.0.2.0/24 \
        --availability-zone "${AWS_REGION}b" \
        --query 'Subnet.SubnetId' \
        --output text)

    private_subnet_1=$(aws ec2 create-subnet \
        --vpc-id "$vpc_id" \
        --cidr-block 10.0.10.0/24 \
        --availability-zone "${AWS_REGION}a" \
        --query 'Subnet.SubnetId' \
        --output text)

    private_subnet_2=$(aws ec2 create-subnet \
        --vpc-id "$vpc_id" \
        --cidr-block 10.0.20.0/24 \
        --availability-zone "${AWS_REGION}b" \
        --query 'Subnet.SubnetId' \
        --output text)

    # Tag subnets
    aws ec2 create-tags --resources "$public_subnet_1" --tags Key=Name,Value="$VPC_NAME-public-1"
    aws ec2 create-tags --resources "$public_subnet_2" --tags Key=Name,Value="$VPC_NAME-public-2"
    aws ec2 create-tags --resources "$private_subnet_1" --tags Key=Name,Value="$VPC_NAME-private-1"
    aws ec2 create-tags --resources "$private_subnet_2" --tags Key=Name,Value="$VPC_NAME-private-2"

    # Create route table for public subnets
    local public_rt
    public_rt=$(aws ec2 create-route-table \
        --vpc-id "$vpc_id" \
        --query 'RouteTable.RouteTableId' \
        --output text)

    aws ec2 create-route \
        --route-table-id "$public_rt" \
        --destination-cidr-block 0.0.0.0/0 \
        --gateway-id "$igw_id"

    aws ec2 associate-route-table --subnet-id "$public_subnet_1" --route-table-id "$public_rt"
    aws ec2 associate-route-table --subnet-id "$public_subnet_2" --route-table-id "$public_rt"

    # Save network configuration
    cat > aws-network-config.txt << EOF
VPC_ID=$vpc_id
IGW_ID=$igw_id
PUBLIC_SUBNET_1=$public_subnet_1
PUBLIC_SUBNET_2=$public_subnet_2
PRIVATE_SUBNET_1=$private_subnet_1
PRIVATE_SUBNET_2=$private_subnet_2
PUBLIC_RT=$public_rt
EOF

    echo "$vpc_id" > vpc-id.txt

    log_success "VPC and networking created"
}

# Create IAM roles
create_iam_roles() {
    log_info "Creating IAM roles..."

    # EKS Cluster Role
    local cluster_role_name="ml-pipeline-eks-cluster-role"
    if aws iam get-role --role-name "$cluster_role_name" &> /dev/null; then
        log_warning "IAM role $cluster_role_name already exists"
    else
        aws iam create-role \
            --role-name "$cluster_role_name" \
            --assume-role-policy-document '{
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {
                            "Service": "eks.amazonaws.com"
                        },
                        "Action": "sts:AssumeRole"
                    }
                ]
            }'

        aws iam attach-role-policy \
            --role-name "$cluster_role_name" \
            --policy-arn arn:aws:iam::aws:policy/AmazonEKSClusterPolicy

        log_success "EKS cluster role created"
    fi

    # EKS Node Group Role
    local nodegroup_role_name="ml-pipeline-eks-nodegroup-role"
    if aws iam get-role --role-name "$nodegroup_role_name" &> /dev/null; then
        log_warning "IAM role $nodegroup_role_name already exists"
    else
        aws iam create-role \
            --role-name "$nodegroup_role_name" \
            --assume-role-policy-document '{
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {
                            "Service": "ec2.amazonaws.com"
                        },
                        "Action": "sts:AssumeRole"
                    }
                ]
            }'

        aws iam attach-role-policy \
            --role-name "$nodegroup_role_name" \
            --policy-arn arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy

        aws iam attach-role-policy \
            --role-name "$nodegroup_role_name" \
            --policy-arn arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy

        aws iam attach-role-policy \
            --role-name "$nodegroup_role_name" \
            --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly

        log_success "EKS node group role created"
    fi

    # ML Pipeline Service Role
    local service_role_name="ml-pipeline-service-role"
    if aws iam get-role --role-name "$service_role_name" &> /dev/null; then
        log_warning "IAM role $service_role_name already exists"
    else
        aws iam create-role \
            --role-name "$service_role_name" \
            --assume-role-policy-document '{
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {
                            "Service": "ec2.amazonaws.com"
                        },
                        "Action": "sts:AssumeRole"
                    }
                ]
            }'

        # Create custom policy for ML pipeline
        aws iam create-policy \
            --policy-name "ml-pipeline-policy" \
            --policy-document '{
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "kinesis:*",
                            "s3:*",
                            "rds:*",
                            "elasticache:*",
                            "logs:*",
                            "cloudwatch:*"
                        ],
                        "Resource": "*"
                    }
                ]
            }' || true  # Ignore if policy already exists

        local account_id
        account_id=$(aws sts get-caller-identity --query Account --output text)

        aws iam attach-role-policy \
            --role-name "$service_role_name" \
            --policy-arn "arn:aws:iam::${account_id}:policy/ml-pipeline-policy"

        log_success "ML pipeline service role created"
    fi
}

# Create EKS cluster
create_eks_cluster() {
    log_info "Creating EKS cluster..."

    if eksctl get cluster --name="$CLUSTER_NAME" --region="$AWS_REGION" &> /dev/null; then
        log_warning "EKS cluster $CLUSTER_NAME already exists"
    else
        # Source network configuration
        source aws-network-config.txt

        # Create cluster configuration file
        cat > eks-cluster-config.yaml << EOF
apiVersion: eksctl.io/v1alpha5
kind: ClusterConfig

metadata:
  name: $CLUSTER_NAME
  region: $AWS_REGION

vpc:
  id: $VPC_ID
  subnets:
    public:
      public-subnet-1:
        id: $PUBLIC_SUBNET_1
      public-subnet-2:
        id: $PUBLIC_SUBNET_2
    private:
      private-subnet-1:
        id: $PRIVATE_SUBNET_1
      private-subnet-2:
        id: $PRIVATE_SUBNET_2

managedNodeGroups:
  - name: ml-pipeline-nodes
    instanceType: m5.large
    minSize: 3
    maxSize: 10
    desiredCapacity: 3
    privateNetworking: true
    labels:
      role: ml-pipeline
    tags:
      Environment: production
      Project: ml-pipeline

addons:
  - name: vpc-cni
  - name: coredns
  - name: kube-proxy
  - name: aws-ebs-csi-driver

cloudWatch:
  clusterLogging:
    enableTypes: ["all"]
EOF

        eksctl create cluster -f eks-cluster-config.yaml

        log_success "EKS cluster created"
    fi

    # Update kubeconfig
    aws eks update-kubeconfig --region "$AWS_REGION" --name "$CLUSTER_NAME"

    # Create namespace
    kubectl create namespace ml-pipeline --dry-run=client -o yaml | kubectl apply -f -

    log_success "EKS cluster configured"
}

# Create RDS instance
create_rds() {
    log_info "Creating RDS PostgreSQL instance..."

    if aws rds describe-db-instances --db-instance-identifier "$DB_INSTANCE_IDENTIFIER" &> /dev/null; then
        log_warning "RDS instance $DB_INSTANCE_IDENTIFIER already exists"
    else
        # Source network configuration
        source aws-network-config.txt

        # Create DB subnet group
        aws rds create-db-subnet-group \
            --db-subnet-group-name ml-pipeline-subnet-group \
            --db-subnet-group-description "Subnet group for ML Pipeline" \
            --subnet-ids "$PRIVATE_SUBNET_1" "$PRIVATE_SUBNET_2" || true

        # Create security group
        local sg_id
        sg_id=$(aws ec2 create-security-group \
            --group-name ml-pipeline-rds-sg \
            --description "Security group for ML Pipeline RDS" \
            --vpc-id "$VPC_ID" \
            --query 'GroupId' \
            --output text 2>/dev/null || \
            aws ec2 describe-security-groups \
                --filters "Name=group-name,Values=ml-pipeline-rds-sg" \
                --query 'SecurityGroups[0].GroupId' \
                --output text)

        # Allow PostgreSQL access
        aws ec2 authorize-security-group-ingress \
            --group-id "$sg_id" \
            --protocol tcp \
            --port 5432 \
            --cidr 10.0.0.0/16 || true

        # Generate random password
        local db_password
        db_password=$(openssl rand -base64 32)

        # Create RDS instance
        aws rds create-db-instance \
            --db-instance-identifier "$DB_INSTANCE_IDENTIFIER" \
            --db-instance-class db.t3.medium \
            --engine postgres \
            --engine-version 15.4 \
            --master-username ml_admin \
            --master-user-password "$db_password" \
            --allocated-storage 50 \
            --storage-type gp2 \
            --storage-encrypted \
            --vpc-security-group-ids "$sg_id" \
            --db-subnet-group-name ml-pipeline-subnet-group \
            --backup-retention-period 7 \
            --multi-az \
            --no-publicly-accessible

        # Save password
        echo "RDS_PASSWORD=$db_password" > aws-rds-password.txt

        log_success "RDS instance creation initiated (this may take several minutes)"
    fi
}

# Create ElastiCache Redis
create_redis() {
    log_info "Creating ElastiCache Redis cluster..."

    if aws elasticache describe-cache-clusters --cache-cluster-id "$REDIS_CLUSTER_ID" &> /dev/null; then
        log_warning "Redis cluster $REDIS_CLUSTER_ID already exists"
    else
        # Source network configuration
        source aws-network-config.txt

        # Create cache subnet group
        aws elasticache create-cache-subnet-group \
            --cache-subnet-group-name ml-pipeline-cache-subnet \
            --cache-subnet-group-description "Cache subnet group for ML Pipeline" \
            --subnet-ids "$PRIVATE_SUBNET_1" "$PRIVATE_SUBNET_2" || true

        # Create security group
        local sg_id
        sg_id=$(aws ec2 create-security-group \
            --group-name ml-pipeline-redis-sg \
            --description "Security group for ML Pipeline Redis" \
            --vpc-id "$VPC_ID" \
            --query 'GroupId' \
            --output text 2>/dev/null || \
            aws ec2 describe-security-groups \
                --filters "Name=group-name,Values=ml-pipeline-redis-sg" \
                --query 'SecurityGroups[0].GroupId' \
                --output text)

        # Allow Redis access
        aws ec2 authorize-security-group-ingress \
            --group-id "$sg_id" \
            --protocol tcp \
            --port 6379 \
            --cidr 10.0.0.0/16 || true

        # Create Redis cluster
        aws elasticache create-cache-cluster \
            --cache-cluster-id "$REDIS_CLUSTER_ID" \
            --cache-node-type cache.t3.medium \
            --engine redis \
            --engine-version 7.0 \
            --num-cache-nodes 1 \
            --cache-subnet-group-name ml-pipeline-cache-subnet \
            --security-group-ids "$sg_id" \
            --at-rest-encryption-enabled \
            --transit-encryption-enabled

        log_success "Redis cluster creation initiated"
    fi
}

# Create Kinesis streams
create_kinesis_streams() {
    log_info "Creating Kinesis streams..."

    local streams=(
        "ml-pipeline-transactions"
        "ml-pipeline-features"
        "ml-pipeline-predictions"
        "ml-pipeline-monitoring"
    )

    for stream in "${streams[@]}"; do
        if aws kinesis describe-stream --stream-name "$stream" &> /dev/null; then
            log_warning "Kinesis stream $stream already exists"
        else
            aws kinesis create-stream \
                --stream-name "$stream" \
                --shard-count 2

            log_success "Created Kinesis stream: $stream"
        fi
    done
}

# Create S3 buckets
create_s3_buckets() {
    log_info "Creating S3 buckets..."

    local account_id
    account_id=$(aws sts get-caller-identity --query Account --output text)

    local buckets=(
        "${S3_BUCKET_PREFIX}-ml-artifacts-${account_id}"
        "${S3_BUCKET_PREFIX}-ml-models-${account_id}"
        "${S3_BUCKET_PREFIX}-ml-data-${account_id}"
        "${S3_BUCKET_PREFIX}-ml-backups-${account_id}"
    )

    for bucket in "${buckets[@]}"; do
        if aws s3 ls "s3://$bucket" &> /dev/null; then
            log_warning "S3 bucket $bucket already exists"
        else
            aws s3 mb "s3://$bucket" --region "$AWS_REGION"

            # Enable versioning
            aws s3api put-bucket-versioning \
                --bucket "$bucket" \
                --versioning-configuration Status=Enabled

            # Set lifecycle policy for backups bucket
            if [[ "$bucket" == *"backups"* ]]; then
                aws s3api put-bucket-lifecycle-configuration \
                    --bucket "$bucket" \
                    --lifecycle-configuration '{
                        "Rules": [
                            {
                                "ID": "DeleteOldBackups",
                                "Status": "Enabled",
                                "Expiration": {
                                    "Days": 90
                                }
                            }
                        ]
                    }'
            fi

            log_success "Created S3 bucket: $bucket"
        fi
    done
}

# Create ECR repositories
create_ecr_repositories() {
    log_info "Creating ECR repositories..."

    local repositories=(
        "ml-pipeline/api"
        "ml-pipeline/beam"
        "ml-pipeline/training"
    )

    for repo in "${repositories[@]}"; do
        if aws ecr describe-repositories --repository-names "$repo" &> /dev/null; then
            log_warning "ECR repository $repo already exists"
        else
            aws ecr create-repository \
                --repository-name "$repo" \
                --image-scanning-configuration scanOnPush=true \
                --encryption-configuration encryptionType=AES256

            log_success "Created ECR repository: $repo"
        fi
    done

    # Get login token
    aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$(aws sts get-caller-identity --query Account --output text).dkr.ecr.${AWS_REGION}.amazonaws.com"
}

# Generate deployment configuration
generate_deployment_config() {
    log_info "Generating deployment configuration..."

    local account_id
    account_id=$(aws sts get-caller-identity --query Account --output text)

    cat > aws-deployment-config.yaml << EOF
# AWS Deployment Configuration
region: $AWS_REGION
account_id: $account_id
cluster_name: $CLUSTER_NAME

# Service endpoints (will be populated after resources are created)
services:
  rds:
    endpoint: "REPLACE_WITH_RDS_ENDPOINT"
    port: 5432
    database: "postgres"
    username: "ml_admin"

  redis:
    endpoint: "REPLACE_WITH_REDIS_ENDPOINT"
    port: 6379

  kinesis:
    region: $AWS_REGION
    streams:
      - ml-pipeline-transactions
      - ml-pipeline-features
      - ml-pipeline-predictions
      - ml-pipeline-monitoring

  s3:
    artifacts_bucket: "${S3_BUCKET_PREFIX}-ml-artifacts-${account_id}"
    models_bucket: "${S3_BUCKET_PREFIX}-ml-models-${account_id}"
    data_bucket: "${S3_BUCKET_PREFIX}-ml-data-${account_id}"
    backups_bucket: "${S3_BUCKET_PREFIX}-ml-backups-${account_id}"

  ecr:
    region: $AWS_REGION
    repositories:
      api: "${account_id}.dkr.ecr.${AWS_REGION}.amazonaws.com/ml-pipeline/api"
      beam: "${account_id}.dkr.ecr.${AWS_REGION}.amazonaws.com/ml-pipeline/beam"
      training: "${account_id}.dkr.ecr.${AWS_REGION}.amazonaws.com/ml-pipeline/training"

# Kubernetes configuration
kubernetes:
  namespace: ml-pipeline
  cluster_name: $CLUSTER_NAME
EOF

    log_success "Deployment configuration saved to aws-deployment-config.yaml"
}

# Main execution
main() {
    log_info "Starting AWS setup for ML Pipeline Platform..."
    log_info "Region: $AWS_REGION"
    log_info "Cluster: $CLUSTER_NAME"

    check_prerequisites
    setup_region
    create_vpc
    create_iam_roles
    create_eks_cluster
    create_rds
    create_redis
    create_kinesis_streams
    create_s3_buckets
    create_ecr_repositories
    generate_deployment_config

    log_success "AWS setup completed successfully!"
    log_info "Next steps:"
    log_info "1. Wait for RDS and Redis instances to be available"
    log_info "2. Update aws-deployment-config.yaml with actual endpoints"
    log_info "3. Update Kubernetes secrets with actual values"
    log_info "4. Build and push Docker images to ECR"
    log_info "5. Deploy the application using: kubectl apply -k k8s/overlays/production"
}

# Show help
if [[ "${1:-}" == "--help" ]] || [[ "${1:-}" == "-h" ]]; then
    cat << EOF
AWS Bootstrap Script for ML Pipeline Platform

Usage: $0 [OPTIONS]

Environment Variables:
  AWS_REGION              AWS Region (default: us-east-1)
  EKS_CLUSTER_NAME        EKS Cluster name (default: ml-pipeline-cluster)
  VPC_NAME                VPC name (default: ml-pipeline-vpc)
  DB_INSTANCE_IDENTIFIER  RDS instance identifier (default: ml-pipeline-postgres)
  REDIS_CLUSTER_ID        Redis cluster ID (default: ml-pipeline-redis)
  S3_BUCKET_PREFIX        S3 bucket prefix (default: ml-pipeline)

Examples:
  # Use defaults
  $0

  # Use custom region
  AWS_REGION=us-west-2 $0

  # Use custom cluster name
  EKS_CLUSTER_NAME=my-ml-cluster $0

This script will:
1. Create VPC and networking
2. Create IAM roles for EKS and services
3. Create EKS cluster
4. Create RDS PostgreSQL instance
5. Create ElastiCache Redis cluster
6. Create Kinesis streams
7. Create S3 buckets
8. Create ECR repositories
9. Generate deployment configuration

Prerequisites:
- AWS CLI installed and configured
- kubectl installed
- eksctl installed
- Docker installed (for ECR login)
- Appropriate AWS permissions
EOF
    exit 0
fi

# Run main function
main "$@"