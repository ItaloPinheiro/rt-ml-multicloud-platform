# =============================================================================
# AWS Demo Environment - Outputs
# =============================================================================
# These values are displayed after `terraform apply` completes
# =============================================================================

# -----------------------------------------------------------------------------
# Instance Information
# -----------------------------------------------------------------------------

output "instance_id" {
  description = "EC2 Instance ID"
  value       = aws_instance.demo.id
}

output "instance_public_ip" {
  description = "Public IP address of the demo instance"
  value       = aws_instance.demo.public_ip
}

output "instance_public_dns" {
  description = "Public DNS name of the demo instance"
  value       = aws_instance.demo.public_dns
}

output "instance_type" {
  description = "Instance type (for cost reference)"
  value       = aws_instance.demo.instance_type
}

output "is_spot_instance" {
  description = "Whether this is a Spot Instance"
  value       = var.use_spot_instance
}

# -----------------------------------------------------------------------------
# SSH Access
# -----------------------------------------------------------------------------

output "ssh_command" {
  description = "SSH command to connect to the instance"
  value       = "ssh -i ${var.key_name}.pem ubuntu@${aws_instance.demo.public_ip}"
}

output "ssh_config_entry" {
  description = "Entry for ~/.ssh/config"
  value       = <<-EOT
    Host ml-demo
        HostName ${aws_instance.demo.public_ip}
        User ubuntu
        IdentityFile ~/.ssh/${var.key_name}.pem
  EOT
}

# -----------------------------------------------------------------------------
# Application URLs
# -----------------------------------------------------------------------------

output "mlflow_url" {
  description = "MLflow Tracking UI URL"
  value       = "http://${aws_instance.demo.public_ip}:${var.nodeport_mlflow}"
}

output "api_url" {
  description = "Model API URL"
  value       = "http://${aws_instance.demo.public_ip}:${var.nodeport_api}"
}

output "api_docs_url" {
  description = "Model API Swagger Documentation"
  value       = "http://${aws_instance.demo.public_ip}:${var.nodeport_api}/docs"
}

output "grafana_url" {
  description = "Grafana Dashboard URL (admin/admin)"
  value       = var.enable_monitoring ? "http://${aws_instance.demo.public_ip}:${var.nodeport_grafana}" : "Monitoring disabled"
}

output "prometheus_url" {
  description = "Prometheus URL"
  value       = var.enable_monitoring ? "http://${aws_instance.demo.public_ip}:${var.nodeport_prometheus}" : "Monitoring disabled"
}

# -----------------------------------------------------------------------------
# Quick Reference
# -----------------------------------------------------------------------------

output "quick_reference" {
  description = "Quick reference for common commands"
  value       = <<-EOT
    
    ============================================================
    🚀 RT ML Platform Demo - Deployment Complete!
    ============================================================
    
    📡 Instance: ${aws_instance.demo.public_ip}
    
    🔗 Service URLs (wait 5-10 min for bootstrap):
       • MLflow:     http://${aws_instance.demo.public_ip}:${var.nodeport_mlflow}
       • API:        http://${aws_instance.demo.public_ip}:${var.nodeport_api}
       • API Docs:   http://${aws_instance.demo.public_ip}:${var.nodeport_api}/docs
       • Grafana:    http://${aws_instance.demo.public_ip}:${var.nodeport_grafana} (admin/admin)
       • Prometheus: http://${aws_instance.demo.public_ip}:${var.nodeport_prometheus}
    
    🔑 SSH Access:
       ssh -i ${var.key_name}.pem ubuntu@${aws_instance.demo.public_ip}
    
    📊 Check Pod Status:
       ssh -i ${var.key_name}.pem ubuntu@${aws_instance.demo.public_ip} \
         "sudo k3s kubectl get pods -n ml-pipeline"
    
    📜 Check Bootstrap Logs:
       ssh -i ${var.key_name}.pem ubuntu@${aws_instance.demo.public_ip} \
         "sudo cat /var/log/cloud-init-output.log | tail -100"
    
    💰 Cost: ~$3.65-10/month (mostly public IPv4)
    
    🛑 CLEANUP (stop paying!):
       terraform destroy -auto-approve
    
    ============================================================
  EOT
}

# -----------------------------------------------------------------------------
# Cost Information
# -----------------------------------------------------------------------------

output "estimated_monthly_cost" {
  description = "Estimated monthly cost breakdown"
  value       = <<-EOT
    
    💰 Estimated Monthly Costs:
    ─────────────────────────────────────────
    Public IPv4:        ~$3.65/month (unavoidable)
    EC2 ${var.instance_type} Spot:  ~$2-4/month (or Free Tier)
    EBS ${var.root_volume_size}GB gp3:       ~$${format("%.2f", var.root_volume_size * 0.08)}/month (or Free Tier)
    ─────────────────────────────────────────
    Total (Free Tier):  ~$3.65/month
    Total (No Free):    ~$8-12/month
    
  EOT
}

# -----------------------------------------------------------------------------
# Cleanup Commands
# -----------------------------------------------------------------------------

output "cleanup_commands" {
  description = "Commands to clean up resources and stop paying"
  value       = <<-EOT
    
    🛑 CLEANUP OPTIONS:
    
    1. DESTROY EVERYTHING (recommended):
       terraform destroy -auto-approve
    
    2. STOP INSTANCE (keeps EBS, ~$2.40/month):
       aws ec2 stop-instances --instance-ids ${aws_instance.demo.id}
    
    3. RESTART STOPPED INSTANCE:
       aws ec2 start-instances --instance-ids ${aws_instance.demo.id}
    
    4. VERIFY NO RESOURCES REMAINING:
       aws ec2 describe-instances --filters "Name=tag:Environment,Values=${var.environment}" \
         --query "Reservations[*].Instances[*].[InstanceId,State.Name]" --output table
    
  EOT
}

# -----------------------------------------------------------------------------
# Infrastructure Details (for debugging)
# -----------------------------------------------------------------------------

output "ami_id" {
  description = "AMI ID used for the instance"
  value       = data.aws_ami.ubuntu.id
}

output "security_group_id" {
  description = "Security Group ID"
  value       = aws_security_group.demo.id
}

output "vpc_id" {
  description = "VPC ID"
  value       = local.vpc_id
}

output "subnet_id" {
  description = "Subnet ID"
  value       = local.subnet_id
}
