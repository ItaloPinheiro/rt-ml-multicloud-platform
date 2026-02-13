# =============================================================================
# AWS Demo Environment - Variables
# =============================================================================
# Zero-cost demo infrastructure for RT ML Platform
# Uses EC2 Spot Instance with K3s for Kubernetes
# =============================================================================

# -----------------------------------------------------------------------------
# AWS Provider Configuration
# -----------------------------------------------------------------------------

variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-east-1"
}

# -----------------------------------------------------------------------------
# Instance Configuration
# -----------------------------------------------------------------------------

variable "instance_type" {
  description = "EC2 instance type. Use t3.micro for Free Tier, t3.small for better performance"
  type        = string
  default     = "t3.micro"

  validation {
    condition     = can(regex("^t[23]\\.(micro|small|medium)$", var.instance_type))
    error_message = "Instance type must be t2.micro, t2.small, t2.medium, t3.micro, t3.small, or t3.medium for demo."
  }
}

variable "use_spot_instance" {
  description = "Use Spot Instance for cost savings (~70% cheaper). Risk: can be terminated with 2-min notice"
  type        = bool
  default     = true
}

variable "root_volume_size" {
  description = "Root EBS volume size in GB. 30GB is Free Tier eligible"
  type        = number
  default     = 30

  validation {
    condition     = var.root_volume_size >= 20 && var.root_volume_size <= 100
    error_message = "Root volume size must be between 20 and 100 GB."
  }
}

variable "root_volume_type" {
  description = "EBS volume type. gp3 is recommended for best price/performance"
  type        = string
  default     = "gp3"

  validation {
    condition     = contains(["gp2", "gp3"], var.root_volume_type)
    error_message = "Volume type must be gp2 or gp3."
  }
}

# -----------------------------------------------------------------------------
# SSH Configuration
# -----------------------------------------------------------------------------

variable "key_name" {
  description = "Name of the AWS Key Pair for SSH access. Must exist in your AWS account"
  type        = string

  validation {
    condition     = length(var.key_name) > 0
    error_message = "Key name is required for SSH access."
  }
}

variable "allowed_ssh_cidrs" {
  description = "CIDR blocks allowed for SSH access. Use your IP for better security (e.g., ['1.2.3.4/32'])"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

# -----------------------------------------------------------------------------
# Environment & Tagging
# -----------------------------------------------------------------------------

variable "environment" {
  description = "Environment name for tagging"
  type        = string
  default     = "demo"
}

variable "project_name" {
  description = "Project name for resource naming and tagging"
  type        = string
  default     = "rt-ml-platform"
}

variable "owner" {
  description = "Owner tag for cost allocation"
  type        = string
  default     = "demo-user"
}

# -----------------------------------------------------------------------------
# Application Configuration
# -----------------------------------------------------------------------------

variable "enable_monitoring" {
  description = "Enable Prometheus and Grafana monitoring stack"
  type        = bool
  default     = true
}

variable "enable_swap" {
  description = "Enable swap file for t3.micro (helps with memory constraints)"
  type        = bool
  default     = true
}

variable "swap_size_gb" {
  description = "Swap file size in GB"
  type        = number
  default     = 2
}

# -----------------------------------------------------------------------------
# Network Configuration
# -----------------------------------------------------------------------------

variable "vpc_cidr" {
  description = "CIDR block for VPC (if creating new VPC)"
  type        = string
  default     = "10.0.0.0/16"
}

variable "use_default_vpc" {
  description = "Use default VPC instead of creating a new one (simpler setup)"
  type        = bool
  default     = true
}

# -----------------------------------------------------------------------------
# NodePort Configuration (K3s Services)
# -----------------------------------------------------------------------------

variable "nodeport_api" {
  description = "NodePort for Model API service"
  type        = number
  default     = 30800
}

variable "nodeport_mlflow" {
  description = "NodePort for MLflow UI"
  type        = number
  default     = 30500
}

variable "nodeport_grafana" {
  description = "NodePort for Grafana dashboard"
  type        = number
  default     = 30300
}

variable "nodeport_prometheus" {
  description = "NodePort for Prometheus"
  type        = number
  default     = 30900
}
