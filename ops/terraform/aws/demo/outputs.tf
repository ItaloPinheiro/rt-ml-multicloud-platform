# =============================================================================
# Outputs
# =============================================================================

output "instance_public_ip" {
  description = "Public IP of the demo EC2 instance"
  value       = aws_instance.demo.public_ip
}

output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.demo.id
}

output "training_data_bucket" {
  description = "S3 bucket name for training data"
  value       = aws_s3_bucket.training_data.bucket
}

output "training_data_bucket_arn" {
  description = "S3 bucket ARN for training data"
  value       = aws_s3_bucket.training_data.arn
}

output "service_urls" {
  description = "Service URLs (replace <IP> with instance_public_ip)"
  value = {
    mlflow     = "http://${aws_instance.demo.public_ip}:${var.nodeport_mlflow}"
    api        = "http://${aws_instance.demo.public_ip}:${var.nodeport_api}"
    api_docs   = "http://${aws_instance.demo.public_ip}:${var.nodeport_api}/docs"
    grafana    = "http://${aws_instance.demo.public_ip}:${var.nodeport_grafana}"
    prometheus = "http://${aws_instance.demo.public_ip}:${var.nodeport_prometheus}"
  }
}

output "ssh_command" {
  description = "SSH command to connect to the instance"
  value       = "ssh -i ~/.ssh/${var.key_name}.pem ubuntu@${aws_instance.demo.public_ip}"
}

output "upload_training_data_command" {
  description = "Command to upload training data to S3"
  value       = "aws s3 cp data/sample/demo/datasets/fraud_detection.csv s3://${aws_s3_bucket.training_data.bucket}/datasets/fraud_detection.csv"
}
