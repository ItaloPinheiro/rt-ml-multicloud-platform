# =============================================================================
# AWS Demo Environment - Main Configuration
# =============================================================================
# Near-Zero Cost demo infrastructure for RT ML Platform
# Uses EC2 Instance (t3.micro) with K3s for lightweight Kubernetes
# =============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# -----------------------------------------------------------------------------
# Provider Configuration
# -----------------------------------------------------------------------------

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
      Owner       = var.owner
    }
  }
}

# -----------------------------------------------------------------------------
# Data Sources
# -----------------------------------------------------------------------------

# Get latest Ubuntu 22.04 LTS AMI
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  filter {
    name   = "state"
    values = ["available"]
  }
}

# Get default VPC (simplest setup)
data "aws_vpc" "default" {
  count   = var.use_default_vpc ? 1 : 0
  default = true
}

# Get default subnets
data "aws_subnets" "default" {
  count = var.use_default_vpc ? 1 : 0

  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default[0].id]
  }

  filter {
    name   = "availability-zone"
    values = ["us-east-1a"]  # Use any supported AZ: a, b, c, d, or f
  }
}

# Get availability zones
data "aws_availability_zones" "available" {
  state = "available"
}

# Current caller identity for unique naming
data "aws_caller_identity" "current" {}

# -----------------------------------------------------------------------------
# Local Variables
# -----------------------------------------------------------------------------

locals {
  name_prefix = "${var.project_name}-${var.environment}"
  vpc_id      = var.use_default_vpc ? data.aws_vpc.default[0].id : aws_vpc.main[0].id
  subnet_id   = var.use_default_vpc ? tolist(data.aws_subnets.default[0].ids)[0] : aws_subnet.public[0].id

  common_tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

# -----------------------------------------------------------------------------
# VPC Resources (only if not using default VPC)
# -----------------------------------------------------------------------------

resource "aws_vpc" "main" {
  count = var.use_default_vpc ? 0 : 1

  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${local.name_prefix}-vpc"
  }
}

resource "aws_internet_gateway" "main" {
  count = var.use_default_vpc ? 0 : 1

  vpc_id = aws_vpc.main[0].id

  tags = {
    Name = "${local.name_prefix}-igw"
  }
}

resource "aws_subnet" "public" {
  count = var.use_default_vpc ? 0 : 1

  vpc_id                  = aws_vpc.main[0].id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, 1)
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true

  tags = {
    Name = "${local.name_prefix}-public-subnet"
  }
}

resource "aws_route_table" "public" {
  count = var.use_default_vpc ? 0 : 1

  vpc_id = aws_vpc.main[0].id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main[0].id
  }

  tags = {
    Name = "${local.name_prefix}-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  count = var.use_default_vpc ? 0 : 1

  subnet_id      = aws_subnet.public[0].id
  route_table_id = aws_route_table.public[0].id
}

# -----------------------------------------------------------------------------
# Security Group
# -----------------------------------------------------------------------------

resource "aws_security_group" "demo" {
  name        = "${local.name_prefix}-sg"
  description = "Security group for RT ML Platform demo"
  vpc_id      = local.vpc_id

  # SSH Access
  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.allowed_ssh_cidrs
  }

  # HTTP (for redirects)
  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # HTTPS
  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # K3s API Server
  ingress {
    description = "K3s API"
    from_port   = 6443
    to_port     = 6443
    protocol    = "tcp"
    cidr_blocks = var.allowed_ssh_cidrs
  }

  # Kubernetes NodePorts (30000-32767)
  ingress {
    description = "Kubernetes NodePorts"
    from_port   = 30000
    to_port     = 32767
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # All outbound traffic
  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# -----------------------------------------------------------------------------
# EC2 Instance
# -----------------------------------------------------------------------------

resource "aws_instance" "demo" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  key_name               = var.key_name
  vpc_security_group_ids = [aws_security_group.demo.id]
  subnet_id              = local.subnet_id
  iam_instance_profile   = aws_iam_instance_profile.ec2_profile.name

  # Spot Instance configuration
  dynamic "instance_market_options" {
    for_each = var.use_spot_instance ? [1] : []
    content {
      market_type = "spot"
      spot_options {
        spot_instance_type = "one-time"
      }
    }
  }

  # Root volume
  root_block_device {
    volume_size           = var.root_volume_size
    volume_type           = var.root_volume_type
    encrypted             = true
    delete_on_termination = true

    tags = {
      Name = "${local.name_prefix}-root-volume"
    }
  }

  # Enable IMDSv2 for security
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  # User data script for bootstrapping
  user_data_base64 = base64encode(templatefile("${path.module}/user-data.sh", {
    enable_swap     = var.enable_swap
    swap_size_gb    = var.swap_size_gb
    enable_monitoring = var.enable_monitoring
    nodeport_api      = var.nodeport_api
    nodeport_mlflow   = var.nodeport_mlflow
    nodeport_grafana  = var.nodeport_grafana
    nodeport_prometheus = var.nodeport_prometheus
  }))

  tags = {
    Name = "${local.name_prefix}-instance"
  }

  lifecycle {
    # Ignore user_data changes to prevent recreation
    ignore_changes = [
      user_data,
      user_data_base64
    ]
  }
}

# -----------------------------------------------------------------------------
# Optional: Elastic IP (for consistent IP across stops/starts)
# Note: This incurs additional cost when instance is stopped
# -----------------------------------------------------------------------------

# Uncomment if you want a static IP that persists across instance stops
# resource "aws_eip" "demo" {
#   instance = aws_instance.demo.id
#   domain   = "vpc"

#   tags = {
#     Name = "${local.name_prefix}-eip"
#   }
# }
