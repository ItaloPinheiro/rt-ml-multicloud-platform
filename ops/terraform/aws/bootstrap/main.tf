# =============================================================================
# Terraform Bootstrap - Remote State Infrastructure
# =============================================================================
# This One-Time setup creates:
# 1. S3 Bucket for storing Terraform State (encrypted, versioned)
# 2. DynamoDB Table for State Locking (prevents concurrent modifications)
# =============================================================================

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project   = "rt-ml-platform"
      Component = "terraform-bootstrap"
      ManagedBy = "terraform-manual-bootstrap"
    }
  }
}

variable "aws_region" {
  description = "AWS Region"
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name"
  default     = "rt-ml-platform"
}

variable "unique_suffix" {
  description = "Unique suffix for globally unique S3 names (update this!)"
  default     = "prod"
}

# -----------------------------------------------------------------------------
# S3 Bucket for State Storage
# -----------------------------------------------------------------------------

resource "aws_s3_bucket" "terraform_state" {
  bucket = "${var.project_name}-tf-state-${var.unique_suffix}"

  # Prevent accidental deletion of this critical state bucket
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "enabled" {
  bucket = aws_s3_bucket.terraform_state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "default" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "public_access" {
  bucket                  = aws_s3_bucket.terraform_state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# -----------------------------------------------------------------------------
# DynamoDB Table for State Locking
# -----------------------------------------------------------------------------

resource "aws_dynamodb_table" "terraform_locks" {
  name         = "${var.project_name}-tf-locks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }
}

# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------

output "s3_bucket_name" {
  value       = aws_s3_bucket.terraform_state.id
  description = "The name of the S3 bucket to use in backend configuration"
}

output "dynamodb_table_name" {
  value       = aws_dynamodb_table.terraform_locks.name
  description = "The name of the DynamoDB table to use in backend configuration"
}
