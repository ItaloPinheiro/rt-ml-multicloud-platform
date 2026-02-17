# AWS Terraform Infrastructure

This directory contains Terraform code for deploying the RT ML Platform to AWS.

## Documentation

*   **[Deployment Guide](../../../docs/terraform/aws-guide.md):** Detailed prerequisites, step-by-step deployment instructions, cost analysis, and troubleshooting.
*   **[Remote State & CI/CD Setup](../../../docs/terraform/remote-state.md):** Instructions for bootstrapping the S3/DynamoDB remote backend and configuring GitHub Actions.

## Quick Reference

### Demo Environment (`demo/`)

**Initialize:**
```bash
cd demo
terraform init
```

**Plan:**
```bash
terraform plan
```

**Apply (Manual):**
```bash
terraform apply
```

**Destroy (Cleanup):**
```bash
terraform destroy -auto-approve
```
