# =============================================================================
# S3 Bucket for Training Data
# =============================================================================
# Stores datasets used by the K8s training Job.
# The EC2 instance (and K8s Jobs running on it) access this via the
# instance profile IAM role.
#
# Structure:
#   s3://<bucket>/datasets/fraud_detection.csv   - training-ready CSV
#   s3://<bucket>/raw/transactions.json          - raw transaction data
# =============================================================================

resource "aws_s3_bucket" "training_data" {
  bucket = "${var.project_name}-training-data-${var.environment}"

  tags = merge(local.common_tags, {
    Name       = "${local.name_prefix}-training-data"
    CostCenter = "ml-training"
  })
}

resource "aws_s3_bucket_versioning" "training_data" {
  bucket = aws_s3_bucket.training_data.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "training_data" {
  bucket = aws_s3_bucket.training_data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "training_data" {
  bucket = aws_s3_bucket.training_data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "training_data" {
  bucket = aws_s3_bucket.training_data.id

  rule {
    id     = "expire-old-versions"
    status = "Enabled"
    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}
