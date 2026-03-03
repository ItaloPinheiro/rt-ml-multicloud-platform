# =============================================================================
# IAM Configuration for EC2 Instance
# =============================================================================

# 1. IAM Role
resource "aws_iam_role" "ec2_role" {
  name = "${local.name_prefix}-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = local.common_tags
}

# 2. IAM Instance Profile
resource "aws_iam_instance_profile" "ec2_profile" {
  name = "${local.name_prefix}-ec2-profile"
  role = aws_iam_role.ec2_role.name
}

# 3. Policy to access Secrets Manager
resource "aws_iam_policy" "secrets_policy" {
  name        = "${local.name_prefix}-secrets-policy"
  description = "Allow EC2 to read GitHub PAT from Secrets Manager"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:rt-ml-platform/*"
      }
    ]
  })
}

# 4. Attach Policy to Role
resource "aws_iam_role_policy_attachment" "secrets_attach" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = aws_iam_policy.secrets_policy.arn
}

# 5. Optional: SSM Policy for Session Manager (Debug access without SSH)
resource "aws_iam_role_policy_attachment" "ssm_attach" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# 6. Policy for S3 training data access (read-only, scoped to training bucket)
# The training data bucket is managed by the bootstrap module, not this demo module.
resource "aws_iam_policy" "training_data_policy" {
  name        = "${local.name_prefix}-training-data-policy"
  description = "Allow EC2 (and K8s Jobs) to read training data from S3"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          data.aws_s3_bucket.training_data.arn,
          "${data.aws_s3_bucket.training_data.arn}/*"
        ]
      }
    ]
  })
}

# 7. Attach S3 training data policy to EC2 role
resource "aws_iam_role_policy_attachment" "training_data_attach" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = aws_iam_policy.training_data_policy.arn
}

# 8. Policy for Apache Beam Pipeline (Kinesis + advanced S3)
resource "aws_iam_policy" "beam_pipeline_policy" {
  name        = "${local.name_prefix}-beam-pipeline-policy"
  description = "Allow EC2 to read/write KDS and advanced S3 ops for beam pipeline"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "kinesis:DescribeStream",
          "kinesis:DescribeStreamSummary",
          "kinesis:GetRecords",
          "kinesis:GetShardIterator",
          "kinesis:ListShards",
          "kinesis:ListStreams",
          "kinesis:SubscribeToShard",
          "kinesis:PutRecord",
          "kinesis:PutRecords"
        ]
        Resource = aws_kinesis_stream.demo_stream.arn
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:PutObjectAcl",
          "s3:GetObject",
          "s3:ListBucket",
          "s3:DeleteObject"
        ]
        Resource = [
          data.aws_s3_bucket.training_data.arn,
          "${data.aws_s3_bucket.training_data.arn}/*"
        ]
      }
    ]
  })
}

# 9. Attach Beam pipeline policy to EC2 role
resource "aws_iam_role_policy_attachment" "beam_pipeline_attach" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = aws_iam_policy.beam_pipeline_policy.arn
}
